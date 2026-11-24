/**
 * Editing and approving a draft unit package (games agent, agents/app/agents/games/editing.py).
 * Kept apart from agentsApi.ts so the check-in screens own their calls.
 */
import {
  agentsFetch,
  decideApproval,
  listApprovals,
  type Approval,
  type GameItem,
  type PackageQuestion,
  type RunResult,
  type TutorMode,
  type UnitPackage,
} from './agentsApi';

/** A deterministic check that failed after an edit (package.check_draft): a nudge, not a blocker. */
export interface PackageWarning {
  target: 'question' | 'item' | 'activity';
  index?: number;          // question: 0-based position
  activity_id?: number;
  item_id?: string | null;
  label: string;           // "Question 2", "Flashcard 3", "Matching"
  note: string;            // "the question gives away the answer"
}

/** GET /unit-package also returns where each question/card came from (a file title, or "teacher"). */
export type EditableQuestion = PackageQuestion & { source?: string };
export type EditableItem = GameItem & { source?: string };

export interface EditedPackage extends UnitPackage {
  questions: EditableQuestion[];
  review?: { edit_warnings?: PackageWarning[]; edited_at?: string } & Record<string, unknown>;
}

export interface PackageSettingsEdit {
  title?: string;
  lesson_date?: string;          // YYYY-MM-DD
  due_date?: string;             // ISO
  due_day?: string;              // YYYY-MM-DD in the teacher's time zone
  tutor_mode?: TutorMode;
  tutor_reveal_after?: number;
  mastery_threshold?: number;    // 0-1
}

/** PATCH body: full question list and/or full item lists per game (item_id kept = same card). */
export interface PackageEdit {
  questions?: EditableQuestion[];
  activities?: Array<{ activity_id: number; items: Array<Partial<EditableItem>> }>;
  settings?: PackageSettingsEdit;
}

export interface PackageEditResult {
  package: EditedPackage;
  warnings: PackageWarning[];
}

export type RegenerateTarget =
  | { kind: 'question'; index: number }
  | { kind: 'item'; activity_id: number; item_id: string };

export interface RegenerateResult extends PackageEditResult {
  replaced: RegenerateTarget;
  generated_by: string;        // "offline" = the no-AI generator
  note: string | null;         // e.g. why the AI path fell back
}

/** 422 = a broken rule (message says which), 409 = not a draft any more. */
export const updateUnitPackage = (packageId: number, edit: PackageEdit) =>
  agentsFetch<PackageEditResult>(`/games/unit-package/${packageId}`, { method: 'PATCH', body: JSON.stringify(edit) });

/** Replace one question or card; 409 with a friendly message when there's nothing new left. */
export const regeneratePackagePart = (packageId: number, target: RegenerateTarget) =>
  agentsFetch<RegenerateResult>(`/games/unit-package/${packageId}/regenerate`, {
    method: 'POST',
    body: JSON.stringify(target),
  });

/** The pending publish_unit_package approval for a package, if it's still waiting. */
export async function findPackageApproval(classId: number, packageId: number): Promise<Approval | null> {
  const { approvals } = await listApprovals(classId, 'pending');
  return approvals.find((a) => a.action_name === 'publish_unit_package'
    && Number(a.action_args.package_id) === packageId) ?? null;
}

/** Approve or reject a draft package from wherever it's shown (same as deciding it in Approvals). */
export async function decideUnitPackage(
  classId: number,
  packageId: number,
  type: 'approve' | 'reject',
  message?: string,
): Promise<{ status: string; result?: RunResult }> {
  const approval = await findPackageApproval(classId, packageId);
  if (!approval) throw new Error("This draft isn't waiting for approval any more. It may have been decided in Approvals.");
  return decideApproval(approval.approval_id, { type, message });
}

/** The agent's closing message after a decision ("Published ... Calendar: added ..."). */
export function decisionOutput(res: { result?: RunResult }): string {
  const out = (res.result as { output?: unknown } | undefined)?.output;
  return typeof out === 'string' ? out : '';
}
