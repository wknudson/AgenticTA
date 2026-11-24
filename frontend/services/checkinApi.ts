/**
 * Student client for flipped-classroom check-ins (docs/flipped-classroom-plan.md, "Appendix:
 * implementation contract"): the practice games (/agents/games/practice/...) and the check-in
 * tutor (/agents/tutor/checkin/...). Every call sends the student's Express JWT as a Bearer token.
 *
 * Errors follow agentsFetch: a string `detail` from FastAPI becomes the message (so a 422
 * "not an honest try" reason can be shown to the student as is). CheckinApiError also carries
 * the HTTP status, so callers can show 422s inline and send 401s back to the login page.
 */
import { API_BASE } from './api';

// ---- Shapes from Express (GET /api/student/assignments/:classId/:assignmentId) ----------------

/** What Express returns as `assignment` when the assignment is a check-in (mode === 'checkin'). */
export interface CheckinAssignmentInfo {
  assignmentId: number;
  classId: number;
  assignmentName: string;
  description: string | null;
  maxPoints: number;
  dueDate: string | null;
  mode: 'checkin';
  unit: string | null;
  lessonDate: string | null;
  tutorMode: TutorMode | null;
  masteryThreshold: number | null;
  pastDue: boolean;
}

export const isCheckinAssignment = (a: unknown): a is CheckinAssignmentInfo =>
  !!a && typeof a === 'object' && (a as { mode?: unknown }).mode === 'checkin';

// ---- Practice (games agent) -------------------------------------------------------------------

export interface FlashcardItem { item_id: string; front: string; back: string }
export interface MatchingItem { item_id: string; term: string; definition: string }
export interface FillInItem { item_id: string; sentence: string; answer: string; alternates?: string[] }

export type GameActivity =
  | { activity_id: number; kind: 'flashcards'; title: string; items: FlashcardItem[] }
  | { activity_id: number; kind: 'matching'; title: string; items: MatchingItem[] }
  | { activity_id: number; kind: 'fill_in'; title: string; items: FillInItem[] };

export type GameKind = GameActivity['kind'];

export interface ItemProgress {
  times_seen: number;
  times_correct: number;
  /** 0/1 from SQLite (a boolean is accepted too). */
  last_correct: number | boolean | null;
  /** Leitner box 1-3: a miss goes back to 1. */
  box: number;
}

export interface PracticeStats {
  mastered: number;
  total: number;
  /** 0-1 */
  mastery: number;
  /** 0-1 */
  threshold: number;
  unlocked: boolean;
  level: number;
  levels: number;
  points: number;
  streak: number;
  best_streak: number;
  answers: number;
  started: boolean;
}

export interface PracticeAnswerResult extends PracticeStats {
  points_awarded: number;
  multiplier: number;
  level_up: boolean;
  just_unlocked: boolean;
}

export interface PracticeState {
  assignment: { assignment_id: number; title: string; unit: string | null; lesson_date: string | null; due_date: string | null };
  activities: GameActivity[];
  /** Keyed "<activity_id>:<item_id>". */
  progress: Record<string, ItemProgress>;
  stats: PracticeStats;
  /** Cards until an item in that box comes back. JSON keys arrive as strings ("1", "2", "3"). */
  replay_gap: Record<string, number>;
}

// ---- Check-in (tutor agent) -------------------------------------------------------------------

export type TutorMode = 'hints_only' | 'answer_after_tries';
export type QuestionStatus = 'unanswered' | 'correct' | 'needs_fix' | 'fixed';
export type HelpLevel = 'none' | 'hint' | 'explained';

export interface CheckinQuestion {
  question_id: number;
  number: number;
  text: string;
  kind: 'choice' | 'explain';
  options?: Array<{ option_id: number; text: string }>;
  status: QuestionStatus;
  first_answer: string | null;
  tries: number;
  help_level: HelpLevel;
  last_feedback: string | null;
  can_reveal: boolean;
}

export interface LearningSignals {
  total: number;
  answered: number;
  resolved: number;
  complete: boolean;
  /** 0-100 */
  completion: number;
  /** 0-100 */
  practice_mastery: number;
  /** 0-100, null until something is answered */
  first_try_accuracy: number | null;
  /** 0-100, null when there was nothing to fix */
  fixed_with_help: number | null;
  understanding: number | null;
  help: Partial<Record<HelpLevel, number>>;
  still_shaky: number[];
}

export interface CheckinState {
  assignment: {
    assignment_id: number;
    title: string;
    unit: string | null;
    tutor_mode: TutorMode;
    tutor_reveal_after: number;
    due_date: string | null;
    lesson_date: string | null;
    max_points: number;
    past_due: boolean;
  };
  practice: PracticeStats;
  unlocked: boolean;
  /** Empty until the practice gate is unlocked. */
  questions: CheckinQuestion[];
  signals: LearningSignals;
}

export interface CheckinAnswerResult { question: CheckinQuestion; correct: boolean; feedback: string | null; signals: LearningSignals }
export interface CheckinFixResult { question: CheckinQuestion; accepted: boolean; feedback: string | null; signals: LearningSignals }
export interface CheckinChatResult { reply: string; question: CheckinQuestion }
export interface TutorMessage { role: string; content: string; created_at?: string }

// ---- Fetch ------------------------------------------------------------------------------------

export class CheckinApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'CheckinApiError';
    this.status = status;
  }
}

async function studentAgentsFetch<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/agents${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...init?.headers },
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err;
    throw new CheckinApiError("Can't reach the server right now. Check your connection and try again.", 0);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail;
    let message: string;
    if (typeof detail === 'string' && detail.trim()) message = detail;
    else if (res.status === 401) message = 'Your login has expired. Please log in again.';
    else if (res.status === 403) message = "You don't have access to this check-in.";
    else if (res.status === 404) message = "We couldn't find this check-in.";
    else message = `Agents service error ${res.status}`;
    throw new CheckinApiError(message, res.status);
  }
  return body as T;
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });

// Practice
export const getPractice = (assignmentId: number, token: string, signal?: AbortSignal) =>
  studentAgentsFetch<PracticeState>(`/games/practice/${assignmentId}`, token, { signal });

export const postPracticeAnswer = (
  assignmentId: number,
  token: string,
  body: { activity_id: number; item_id: string; correct: boolean },
) => studentAgentsFetch<PracticeAnswerResult>(`/games/practice/${assignmentId}/answer`, token, json(body));

// Check-in
export const getCheckin = (assignmentId: number, token: string, signal?: AbortSignal) =>
  studentAgentsFetch<CheckinState>(`/tutor/checkin/${assignmentId}`, token, { signal });

export const postCheckinAnswer = (
  assignmentId: number,
  token: string,
  body: { question_id: number; option_id?: number; text?: string },
) => studentAgentsFetch<CheckinAnswerResult>(`/tutor/checkin/${assignmentId}/answer`, token, json(body));

export const postCheckinFix = (
  assignmentId: number,
  token: string,
  body: { question_id: number; option_id?: number; explanation: string },
) => studentAgentsFetch<CheckinFixResult>(`/tutor/checkin/${assignmentId}/fix`, token, json(body));

export const postCheckinChat = (
  assignmentId: number,
  token: string,
  body: { question_id: number; message: string },
) => studentAgentsFetch<CheckinChatResult>(`/tutor/checkin/${assignmentId}/chat`, token, json(body));

export const getCheckinChat = (assignmentId: number, questionId: number, token: string, signal?: AbortSignal) =>
  studentAgentsFetch<{ messages: TutorMessage[] }>(`/tutor/checkin/${assignmentId}/chat/${questionId}`, token, { signal });

/** A tutor transcript row written by the student (the service may use "user" or "student"). */
export const isStudentMessage = (m: TutorMessage) => m.role === 'user' || m.role === 'student' || m.role === 'human';
