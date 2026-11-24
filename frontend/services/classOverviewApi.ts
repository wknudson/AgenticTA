/**
 * Teacher dashboard overview calls (Assignments list rows, the Approvals badge, the Library's
 * "has a check-in" marks, and a student's check-ins in Metrics).
 * Backend: agents/app/agents/misconceptions/briefing.py, GET /checkins.
 */
import { agentsFetch, listApprovals, type CheckinStage, type CheckinSummary } from './agentsApi';

/** live = open; due_soon = due within 24 hours; closed = past the due date. */
export type CheckinStatus = 'live' | 'due_soon' | 'closed';

/** Active students by stage (same rules as the briefing's roster). */
export type CheckinCounts = Record<CheckinStage, number> & { total: number };

export interface CheckinOverviewRow extends CheckinSummary {
  counts: CheckinCounts;
  status: CheckinStatus;
}

/** A unit package still waiting for its publish approval. */
export interface CheckinDraft {
  package_id: number;
  unit: string;
  title: string;
  lesson_date: string | null;
  due_date: string | null;
  created_at: string;
}

export interface ClassCheckinOverview {
  checkins: CheckinOverviewRow[];
  drafts: CheckinDraft[];
}

export const getCheckinOverview = (classId: number, signal?: AbortSignal) =>
  agentsFetch<ClassCheckinOverview>(`/misconceptions/checkins?class_id=${classId}&overview=true`, { signal });

/** One student's place in a check-in. Percentages are 0-100; null = nothing to measure yet. */
export interface StudentCheckinProgress {
  stage: CheckinStage;
  answered: number;
  resolved: number;
  total: number;
  completion: number;
  practice_mastery: number;
  first_try_accuracy: number | null;
  fixed_with_help: number | null;
  understanding: number | null;
}

export interface StudentCheckinRow extends CheckinSummary {
  student: StudentCheckinProgress;
}

/** 404 when the student isn't (or is no longer) active in the class. */
export const getStudentCheckins = (classId: number, studentId: number, signal?: AbortSignal) =>
  agentsFetch<{ checkins: StudentCheckinRow[] }>(
    `/misconceptions/checkins?class_id=${classId}&student_id=${studentId}`,
    { signal },
  );

export const countPendingApprovals = async (classId: number): Promise<number> =>
  (await listApprovals(classId, 'pending')).approvals.length;
