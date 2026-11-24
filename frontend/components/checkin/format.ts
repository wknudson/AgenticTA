/** Small display helpers shared by the teacher's check-in screens. */
import type { CheckinStage, TutorMode } from '../../services/agentsApi';

/** 'YYYY-MM-DD' -> "Thu, Dec 3" (read as a local date, so it never shifts a day). */
export function formatDay(day: string | null | undefined, withYear = false): string {
  if (!day) return '';
  const d = new Date(`${day.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return day;
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', ...(withYear ? { year: 'numeric' } : {}) });
}

/** ISO timestamp -> "Wed, Dec 2, 11:59 PM". */
export function formatDue(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export const pct = (share: number | null | undefined) => (share == null ? '–' : `${Math.round(share * 100)}%`);

export function tutorModeLabel(mode: TutorMode | string | undefined, revealAfter?: number): string {
  if (mode === 'answer_after_tries') return `Answer after ${revealAfter ?? 2} honest ${revealAfter === 1 ? 'try' : 'tries'}`;
  return 'Hints only';
}

export const STAGE_LABEL: Record<CheckinStage, string> = {
  not_started: 'Not started',
  practicing: 'Practicing',
  checkin: 'Check-in in progress',
  complete: 'Complete',
};

export const STAGE_STYLE: Record<CheckinStage, { dot: string; tile: string }> = {
  not_started: { dot: 'bg-gray-400', tile: 'border-gray-200 bg-gray-50 text-gray-800' },
  practicing: { dot: 'bg-amber-500', tile: 'border-amber-200 bg-amber-50 text-amber-900' },
  checkin: { dot: 'bg-sky-500', tile: 'border-sky-200 bg-sky-50 text-sky-900' },
  complete: { dot: 'bg-emerald-500', tile: 'border-emerald-200 bg-emerald-50 text-emerald-900' },
};

export const GAME_LABEL: Record<string, string> = {
  flashcards: 'Flashcards',
  matching: 'Matching',
  fill_in: 'Fill in the blank',
};

// The briefing remembers which check-in the teacher last looked at (per class, this browser tab),
// and the Assignments list uses the same key to open the briefing on a specific check-in.
const briefingKey = (classId: number) => `lyrning_briefing_checkin_${classId}`;

export function rememberBriefingCheckin(classId: number, assignmentId: number): void {
  try { window.sessionStorage.setItem(briefingKey(classId), String(assignmentId)); } catch { /* storage unavailable */ }
}

export function rememberedBriefingCheckin(classId: number): number | null {
  try {
    const n = Number(window.sessionStorage.getItem(briefingKey(classId)));
    return n > 0 ? n : null;
  } catch {
    return null;
  }
}

/** Local YYYY-MM-DD for a Date. */
export function isoDay(d: Date): string {
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

/** The evening before a lesson, as a datetime-local value ("YYYY-MM-DDT23:59"). */
export function eveningBefore(lessonDay: string): string {
  const d = new Date(`${lessonDay}T00:00:00`);
  if (Number.isNaN(d.getTime())) return '';
  d.setDate(d.getDate() - 1);
  return `${isoDay(d)}T23:59`;
}
