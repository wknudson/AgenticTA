/**
 * Client for the Python agents service.  In dev, Vite proxies /agents -> http://127.0.0.1:8000.
 * Agent owners add their own calls at the bottom of this file (or in their panel file).
 */
import { API_BASE } from './api';

export interface AgentModel {
  provider: string;
  model: string;
  key_set: boolean;
}

export interface AgentInfo {
  name: string;
  title: string;
  owner: string | null;
  kind: string | null;
  pattern: string | null;
  models: Record<string, AgentModel>;
  ready: boolean;
  langsmith_project: string;
}

export interface AgentsHealth {
  status: string;
  db_path: string;
  keys: Record<string, boolean>;
  agents: AgentInfo[];
}

export interface Approval {
  approval_id: number;
  group_id: string;
  position: number;
  agent: string;
  class_id: number | null;
  action_name: string;
  action_args: Record<string, unknown>;
  description: string | null;
  allowed_decisions: Array<'approve' | 'edit' | 'reject'>;
  required_role: 'teacher' | 'admin';
  status: 'pending' | 'approved' | 'edited' | 'rejected';
  created_at: string;
}

export type RunResult =
  | { status: 'waiting_for_approval'; thread_id: string; approval_groups: string[] }
  | { status: 'done'; thread_id: string; output: string | null }
  | Record<string, unknown>;

export async function agentsFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/agents${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init?.headers },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new Error(typeof detail === 'string' ? detail : `Agents service error ${res.status}`);
  }
  return body as T;
}

export const getAgentsHealth = () => agentsFetch<AgentsHealth>('/health');

export const runAgentDemo = (agent: string, classId: number, extraQuery = '') =>
  agentsFetch<RunResult>(`/${agent}/demo?class_id=${classId}${extraQuery}`, { method: 'POST' });

export const listApprovals = (classId: number, status: string = 'pending') =>
  agentsFetch<{ approvals: Approval[] }>(`/approvals?class_id=${classId}&status=${encodeURIComponent(status)}`);

export const decideApproval = (
  approvalId: number,
  decision: { type: 'approve' | 'edit' | 'reject'; edited_args?: Record<string, unknown>; message?: string },
) =>
  agentsFetch<{ status: string; result?: RunResult }>(`/approvals/${approvalId}/decide`, {
    method: 'POST',
    body: JSON.stringify({ ...decision, decided_by: 'teacher', role: 'teacher' }),
  });

// ---------------------------------------------------------------- Flipped classroom (teacher side)
// docs/flipped-classroom-plan.md, "Appendix: implementation contract".

export type TutorMode = 'hints_only' | 'answer_after_tries';

/** GET /agents/filing/units: Library folders for a class (unit null = not filed under a unit). */
export interface LibraryUnit {
  unit: string | null;
  total: number;
  by_type: Record<string, number>;
}

export const listLibraryUnits = (classId: number, signal?: AbortSignal) =>
  agentsFetch<{ units: LibraryUnit[]; doc_types: string[] }>(`/filing/units?class_id=${classId}`, { signal });

export interface UnitPackageRequest {
  class_id: number;
  unit: string;
  lesson_date: string;            // YYYY-MM-DD
  due_date?: string;              // ISO; the agent defaults it to the day before the lesson, 23:59
  due_day?: string;               // YYYY-MM-DD in the teacher's time zone (the calendar entry's day)
  title?: string;
  tutor_mode: TutorMode;
  tutor_reveal_after: number;
  mastery_threshold: number;      // 0-1
  mc_count: number;
  explain_count: number;
  card_count?: number;
  offline: boolean;               // true = no-AI draft
}

export interface UnitPackageSummary {
  flashcards: number;
  matching: number;
  fill_in: number;
  mc: number;
  explain: number;
  generated_by: string;
}

export interface UnitPackageCreated {
  status: 'waiting_for_approval';
  thread_id: string;
  approval_groups: string[];
  package_id: number;
  summary: UnitPackageSummary;
}

export const createUnitPackage = (body: UnitPackageRequest) =>
  agentsFetch<UnitPackageCreated>('/games/unit-package', { method: 'POST', body: JSON.stringify(body) });

/** One game card. Flashcards: front/back; matching: term/definition; fill_in: sentence/answer. */
export interface GameItem {
  item_id: string;
  front?: string;
  back?: string;
  term?: string;
  definition?: string;
  sentence?: string;
  answer?: string;
  alternates?: string[];
}

export interface PackageActivity {
  activity_id: number;
  kind: 'flashcards' | 'matching' | 'fill_in' | string;
  title: string;
  items: GameItem[];
}

export interface PackageQuestion {
  text: string;
  kind: 'choice' | 'explain';
  options?: Array<{ text: string; correct: boolean }>;
  answer?: string;   // explain: the model answer (teacher-only)
  rubric?: string;   // explain: what a good explanation must mention
}

export interface UnitPackage {
  package_id: number;
  class_id: number;
  unit: string;
  status: 'draft' | 'published' | 'rejected' | string;
  settings: Partial<Omit<UnitPackageRequest, 'class_id' | 'unit'>> & Record<string, unknown>;
  generated_by: string | null;
  activities: PackageActivity[];
  questions: PackageQuestion[];
  assignment_id: number | null;
}

export const getUnitPackage = (packageId: number, signal?: AbortSignal) =>
  agentsFetch<UnitPackage>(`/games/unit-package/${packageId}`, { signal });

/** The package a published check-in was built from (404 for check-ins made some other way). */
export const getUnitPackageForAssignment = (assignmentId: number, signal?: AbortSignal) =>
  agentsFetch<UnitPackage>(`/games/unit-package/by-assignment/${assignmentId}`, { signal });

// ---- Before-class briefing (misconceptions agent)

export type CheckinStage = 'not_started' | 'practicing' | 'checkin' | 'complete';
export type HelpLevel = 'none' | 'hint' | 'explained';

export interface CheckinSummary {
  assignment_id: number;
  title: string;
  unit: string | null;
  lesson_date: string | null;
  due_date: string | null;
}

/** app/shared/checkin.py learning_signals(); percentages are 0-100, null = nothing to measure yet. */
export interface LearningSignals {
  total: number;
  answered: number;
  resolved: number;
  complete: boolean;
  completion: number;
  practice_mastery: number;
  first_try_accuracy: number | null;
  fixed_with_help: number | null;
  understanding: number | null;
  help: Record<HelpLevel, number>;
  still_shaky: number[];
}

export interface RosterEntry {
  student_id: number;
  name: string;
  stage: CheckinStage;
  mastery: number;      // 0-1 share of game cards mastered
  unlocked: boolean;
  answered: number;
  resolved: number;
  total: number;
}

export interface HardestQuestion {
  question_id: number;
  number: number;
  text: string;
  kind: 'choice' | 'explain';
  answered: number;
  first_try_rate: number;   // 0-1
  misses: number;
  explained: number;        // times the tutor had to explain the answer
  still_open: number;
}

export interface HardestItem {
  activity_id: number;
  item_id: string;
  kind: string | null;
  label: string;
  answer: string | null;
  misses: number;
  seen: number;
  still_missing: number;
  students: number;
}

export interface MissedQuestion {
  question_id: number;
  number: number;
  text: string;
  kind: 'choice' | 'explain';
  first_answer: string | null;
  help_level: HelpLevel;
  explain_back: string | null;
  status: 'needs_fix' | 'fixed';
  tries: number;
}

export interface StudentStruggles {
  student_id: number;
  name: string;
  stage: CheckinStage;
  signals: LearningSignals;
  missed: MissedQuestion[];
}

export interface MisconceptionInsight {
  insight_id: number;
  class_id: number;
  assignment_id: number | null;
  topic: string;
  evidence_count: number;
  examples: string[];
  suggestion: { explanation: string; material_update: string; reteaching_activity: string; supporting_student_count?: number };
  model_used: string | null;
  status: string;
  created_at: string;
}

export type WarmupBasis =
  | { kind: 'question'; question_id: number; number: number; text: string; first_try_rate: number }
  | { kind: 'misconception'; insight_id: number; topic: string };

export interface Warmup {
  questions: string[];
  reteach: string;
  based_on: WarmupBasis[];
  model_used: string | null;   // "deterministic" = built without AI
  edited: boolean;
  created_at: string;
}

export interface Briefing {
  assignment: {
    assignment_id: number;
    title: string;
    unit: string | null;
    lesson_date: string | null;
    due_date: string | null;
    past_due: boolean;
    tutor_mode: TutorMode;
    tutor_reveal_after: number;
    mastery_threshold: number;
    max_points: number;
    question_count: number;
    item_count: number;
  };
  roster: RosterEntry[];
  counts: Record<CheckinStage, number> & { total: number };
  hardest_questions: HardestQuestion[];
  hardest_items: HardestItem[];
  students: StudentStruggles[];
  misconceptions: MisconceptionInsight[];
  warmup: Warmup | null;
}

export interface MisconceptionRun {
  chats_read: number;
  questions_analyzed: number;
  insights_found: number;
  insights_suppressed: number;
  latency_seconds: number;
}

export const listCheckins = (classId: number, signal?: AbortSignal) =>
  agentsFetch<{ checkins: CheckinSummary[] }>(`/misconceptions/checkins?class_id=${classId}`, { signal });

export const getBriefing = (classId: number, assignmentId: number, signal?: AbortSignal) =>
  agentsFetch<Briefing>(`/misconceptions/briefing?class_id=${classId}&assignment_id=${assignmentId}`, { signal });

export const generateWarmup = (classId: number, assignmentId: number, offline = false) =>
  agentsFetch<Warmup>(
    `/misconceptions/briefing/warmup?class_id=${classId}&assignment_id=${assignmentId}${offline ? '&offline=true' : ''}`,
    { method: 'POST' },
  );

export const saveWarmup = (classId: number, assignmentId: number, warmup: { questions: string[]; reteach: string }) =>
  agentsFetch<Warmup>(`/misconceptions/briefing/warmup?class_id=${classId}&assignment_id=${assignmentId}`, {
    method: 'PUT',
    body: JSON.stringify(warmup),
  });

/** The misconception finder on one check-in's tutor chats (local model; 503 when Ollama isn't running). */
export const runMisconceptionFinder = (classId: number, assignmentId: number) =>
  agentsFetch<MisconceptionRun>(`/misconceptions/run?class_id=${classId}&assignment_id=${assignmentId}`, { method: 'POST' });
