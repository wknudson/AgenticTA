/** Turns the scheduler feed into per-day items for the class calendar and its day panel. */
import type { FeedAssignment, FeedCheckin, FeedDraft, FeedEvent } from '../../../services/schedulerFeedApi';
import { isoDay } from '../../checkin/format';
import { parseISO, toISO } from './calendarUtils';

export interface DayItems {
  /** Check-ins whose lesson is this day. */
  lessons: FeedCheckin[];
  /** Check-ins due this day. */
  dues: FeedCheckin[];
  /** Check-ins whose practice window covers this day. */
  windows: FeedCheckin[];
  events: FeedEvent[];
  /** Graded assignments due this day (not already shown as a scheduler event). */
  assignments: FeedAssignment[];
  draftLessons: FeedDraft[];
  draftDues: FeedDraft[];
}

export const emptyDay = (): DayItems => ({
  lessons: [], dues: [], windows: [], events: [], assignments: [], draftLessons: [], draftDues: [],
});

/** 'YYYY-MM-DD' from a day or ISO string, or null. */
export const dayOf = (s: string | null | undefined): string | null => (s ? s.slice(0, 10) : null);

/** The teacher's local calendar day for an ISO instant. */
export const localDay = (iso: string | null | undefined): string | null => {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : isoDay(d);
};

export const addDays = (iso: string, n: number) => {
  const d = parseISO(iso);
  d.setUTCDate(d.getUTCDate() + n);
  return toISO(d);
};

export const daysBetween = (a: string, b: string) =>
  Math.round((parseISO(b).getTime() - parseISO(a).getTime()) / 86_400_000);

export const checkinDueDay = (c: FeedCheckin) => dayOf(c.due_day) ?? localDay(c.due_date);

/** The practice window (open_day to the due day, else the lesson), or null. */
export const practiceWindow = (c: FeedCheckin): { start: string; end: string } | null => {
  const start = dayOf(c.open_day);
  const end = checkinDueDay(c) ?? dayOf(c.lesson_date);
  if (!start || !end || start > end) return null;
  return { start, end };
};

export interface FeedParts {
  events: FeedEvent[];
  checkins: FeedCheckin[];
  drafts: FeedDraft[];
  assignments: FeedAssignment[];
}

export function buildDayIndex({ events, checkins, drafts, assignments }: FeedParts): Record<string, DayItems> {
  const map: Record<string, DayItems> = {};
  const at = (d: string) => (map[d] ??= emptyDay());
  for (const c of checkins) {
    const lesson = dayOf(c.lesson_date);
    if (lesson) at(lesson).lessons.push(c);
    const due = checkinDueDay(c);
    if (due) at(due).dues.push(c);
    const w = practiceWindow(c);
    if (w) {
      const n = Math.min(daysBetween(w.start, w.end), 366);
      for (let i = 0; i <= n; i += 1) at(addDays(w.start, i)).windows.push(c);
    }
  }
  for (const e of events) at(dayOf(e.date) ?? e.date).events.push(e);
  for (const d of drafts) {
    const lesson = dayOf(d.lesson_date);
    if (lesson) at(lesson).draftLessons.push(d);
    const due = dayOf(d.due_day);
    if (due) at(due).draftDues.push(d);
  }
  // A scheduler event tied to a graded assignment ("X due") stands for it: show one chip, the event
  // (it has a status and kind, and can be dragged).
  const shownAsEvent = new Set(events.map((e) => e.assignment_id).filter((id): id is number => id != null));
  for (const a of assignments) {
    const day = localDay(a.due_date);
    if (!day || shownAsEvent.has(a.assignment_id)) continue;
    at(day).assignments.push(a);
  }
  return map;
}

/** One lane per overlapping practice window (assignment_id -> lane, 0-based), greedy by start day. */
export function practiceLanes(checkins: FeedCheckin[]): Map<number, number> {
  const rows = checkins
    .map((c) => ({ c, w: practiceWindow(c) }))
    .filter((r): r is { c: FeedCheckin; w: { start: string; end: string } } => r.w !== null)
    .sort((a, b) => a.w.start.localeCompare(b.w.start) || a.c.assignment_id - b.c.assignment_id);
  const ends: string[] = [];
  const lanes = new Map<number, number>();
  for (const { c, w } of rows) {
    let lane = ends.findIndex((end) => end < w.start);
    if (lane === -1) { lane = ends.length; ends.push(w.end); } else ends[lane] = w.end;
    lanes.set(c.assignment_id, lane);
  }
  return lanes;
}

/** Colors that tie a check-in's practice band, lesson chip and due chip together (none clash with event kinds). */
export const CHECKIN_PALETTE = [
  { band: 'bg-violet-200 text-violet-900', chip: 'bg-violet-50 text-violet-900 border-violet-300', dot: 'bg-violet-500' },
  { band: 'bg-teal-200 text-teal-900', chip: 'bg-teal-50 text-teal-900 border-teal-300', dot: 'bg-teal-500' },
  { band: 'bg-fuchsia-200 text-fuchsia-900', chip: 'bg-fuchsia-50 text-fuchsia-900 border-fuchsia-300', dot: 'bg-fuchsia-500' },
  { band: 'bg-orange-200 text-orange-900', chip: 'bg-orange-50 text-orange-900 border-orange-300', dot: 'bg-orange-500' },
  { band: 'bg-indigo-200 text-indigo-900', chip: 'bg-indigo-50 text-indigo-900 border-indigo-300', dot: 'bg-indigo-500' },
] as const;

export type CheckinColor = (typeof CHECKIN_PALETTE)[number];

export function checkinColors(checkins: FeedCheckin[]): Map<number, CheckinColor> {
  const sorted = [...checkins].sort((a, b) =>
    (dayOf(a.open_day) ?? dayOf(a.lesson_date) ?? '').localeCompare(dayOf(b.open_day) ?? dayOf(b.lesson_date) ?? '')
    || a.assignment_id - b.assignment_id);
  return new Map(sorted.map((c, i) => [c.assignment_id, CHECKIN_PALETTE[i % CHECKIN_PALETTE.length]]));
}

/**
 * The due for a lesson moved to `lessonDay`: the evening before the new lesson, at the old due's
 * local time (23:59 when there was none). due_day is the teacher's local day.
 */
export function dueBeforeLesson(lessonDay: string, oldDueIso: string | null): { due_date: string; due_day: string } {
  const d = new Date(`${lessonDay}T00:00:00`);
  d.setDate(d.getDate() - 1);
  let hours = 23;
  let minutes = 59;
  const old = oldDueIso ? new Date(oldDueIso) : null;
  if (old && !Number.isNaN(old.getTime())) { hours = old.getHours(); minutes = old.getMinutes(); }
  d.setHours(hours, minutes, 0, 0);
  return { due_date: d.toISOString(), due_day: isoDay(d) };
}

export const STATUS_CHIP: Record<string, { label: string; cls: string }> = {
  live: { label: 'Live', cls: 'bg-emerald-50 text-emerald-800 border-emerald-200' },
  due_soon: { label: 'Due soon', cls: 'bg-amber-50 text-amber-800 border-amber-200' },
  closed: { label: 'Closed', cls: 'bg-gray-100 text-gray-600 border-gray-200' },
};
