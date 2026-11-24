/**
 * Teacher settings for a published unit check-in (tutor agent), plus the scheduler reads the
 * lesson-day picker needs. See agents/app/agents/tutor/checkin_settings.py.
 */
import { agentsFetch, type TutorMode } from './agentsApi';
import type { CalendarEvent, Term } from '../components/agents/calendar/calendarUtils';

export interface CheckinCalendarEvent {
  event_id: number;
  date: string; // YYYY-MM-DD
  title: string;
  status: 'published' | 'proposed' | string;
}

export interface CheckinSettings {
  assignment_id: number;
  class_id: number;
  title: string;
  unit: string | null;
  lesson_date: string | null; // YYYY-MM-DD
  due_date: string | null; // ISO instant (UTC)
  /** The calendar entry's day, else the UTC day of due_date. */
  due_day: string | null;
  tutor_mode: TutorMode;
  tutor_reveal_after: number;
  /** Share of practice items mastered to unlock the check-in, 0.1-1. */
  mastery_threshold: number;
  past_due: boolean;
  calendar_event: CheckinCalendarEvent | null;
  /** Students who already unlocked the check-in (they keep it whatever the threshold). */
  unlocked_students: number;
}

/** Only the fields to change. due_date is an ISO instant; due_day is the teacher's local YYYY-MM-DD for it. */
export interface CheckinSettingsPatch {
  title?: string;
  lesson_date?: string;
  due_date?: string;
  due_day?: string;
  tutor_mode?: TutorMode;
  tutor_reveal_after?: number;
  /** 0.1-1, or 10-100 as a percent. */
  mastery_threshold?: number;
}

export interface CheckinSettingsSaved {
  settings: CheckinSettings;
  changed: string[];
  notes: string[];
  calendar_note: string | null;
}

export const getCheckinSettings = (assignmentId: number, signal?: AbortSignal) =>
  agentsFetch<{ settings: CheckinSettings }>(`/tutor/checkin/${assignmentId}/settings`, { signal });

export const updateCheckinSettings = (assignmentId: number, patch: CheckinSettingsPatch) =>
  agentsFetch<CheckinSettingsSaved>(`/tutor/checkin/${assignmentId}/settings`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });

/** The class's term (null until the teacher saves one in the Scheduler). */
export const getClassTerm = (classId: number, signal?: AbortSignal) =>
  agentsFetch<{ term: Term | null }>(`/scheduler/term?class_id=${classId}`, { signal });

/** Published calendar events (what students see), for the lesson-day picker. */
export const getPublishedEvents = (classId: number, signal?: AbortSignal) =>
  agentsFetch<{ events: CalendarEvent[] }>(`/scheduler/events?class_id=${classId}&status=published`, { signal });
