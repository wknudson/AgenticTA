/**
 * The Scheduler tab's class calendar: everything dated for one class in one call (the feed), and
 * the scheduler's check-in suggestions. Backend: agents/app/agents/scheduler (GET /feed,
 * GET /checkin-suggestions). Moves go through the existing endpoints:
 * PATCH /scheduler/events/{id} (events) and checkinSettingsApi.updateCheckinSettings (check-ins).
 */
import { agentsFetch } from './agentsApi';
import type { CalendarEvent, Term } from '../components/agents/calendar/calendarUtils';
import type { CheckinCounts, CheckinStatus } from './classOverviewApi';

/** A scheduler event (quiz, lab, reading...). Check-in-owned events are not in the feed. */
export interface FeedEvent extends CalendarEvent {
  status: 'published' | 'proposed' | string;
  assignment_id: number | null;
  source: string | null;
}

/** A published unit check-in: lesson day, due, and the practice window (open_day to due_day). */
export interface FeedCheckin {
  assignment_id: number;
  title: string;
  unit: string | null;
  lesson_date: string | null; // YYYY-MM-DD
  due_date: string | null; // ISO instant
  due_day: string | null; // YYYY-MM-DD (the teacher's day for the due date)
  open_day: string | null; // YYYY-MM-DD, when practice opens
  status: CheckinStatus;
  counts: CheckinCounts;
  calendar_event_id: number | null;
}

/** A unit package (check-in) waiting for its publish approval. */
export interface FeedDraft {
  package_id: number;
  unit: string;
  title: string;
  lesson_date: string | null;
  due_day: string | null;
}

/** A graded assignment with a due date. Its calendar day is the LOCAL date of due_date. */
export interface FeedAssignment {
  assignment_id: number;
  title: string;
  type: string;
  due_date: string | null; // ISO
}

export interface SchedulerFeed {
  term: Term | null;
  events: FeedEvent[];
  checkins: FeedCheckin[];
  drafts: FeedDraft[];
  assignments: FeedAssignment[];
}

export const getSchedulerFeed = (classId: number, start: string, end: string, signal?: AbortSignal) =>
  agentsFetch<SchedulerFeed>(
    `/scheduler/feed?class_id=${classId}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    { signal },
  );

export interface CheckinSuggestionAnchor {
  title: string;
  date: string;
  kind: string;
  source: string | null;
}

export interface CheckinSuggestion {
  unit: string;
  lesson_date: string;
  due_day: string;
  reason: string;
  anchor: CheckinSuggestionAnchor | null;
}

export interface CheckinSuggestions {
  suggestions: CheckinSuggestion[];
  skipped: Array<{ unit: string; reason: string }>;
}

export const getCheckinSuggestions = (classId: number, signal?: AbortSignal) =>
  agentsFetch<CheckinSuggestions>(`/scheduler/checkin-suggestions?class_id=${classId}`, { signal });

/** Move a scheduler event to another day (the scheduler rechecks its rules; 409 with the reason if not). */
export const moveSchedulerEvent = (classId: number, eventId: number, date: string) =>
  agentsFetch<{ event: CalendarEvent }>(`/scheduler/events/${eventId}?class_id=${classId}`, {
    method: 'PATCH',
    body: JSON.stringify({ date }),
  });
