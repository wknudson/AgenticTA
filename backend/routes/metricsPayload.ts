/**
 * Shapes one weekly `student_metrics` row (or a class/global average of them) for the
 * teacher and admin metrics endpoints. Learning signals replace the old AI Dependency score
 * (docs/flipped-classroom-plan.md section 6). Every value is 0-100, or null when the week has
 * no data for it (practice / first-try / fixed-with-help are null for legacy graded work).
 */
export interface WeeklySignals {
  /** first-try accuracy on check-ins, the score on legacy graded work */
  accuracy: number | null;
  understanding: number | null;
  /** practice mastery: share of game items mastered */
  practice: number | null;
  firstTryAccuracy: number | null;
  /** share of missed check-in questions the student fixed with the tutor */
  fixedWithHelp: number | null;
}

const num = (v: unknown): number | null => (v == null || v === '' ? null : Number(v));

/** Accepts the raw column names (accuracy_score, understanding_score, practice_score, first_try_accuracy, fixed_with_help). */
export function weeklySignals(row: Record<string, unknown> | null | undefined): WeeklySignals {
  return {
    accuracy: num(row?.accuracy_score),
    understanding: num(row?.understanding_score),
    practice: num(row?.practice_score),
    firstTryAccuracy: num(row?.first_try_accuracy),
    fixedWithHelp: num(row?.fixed_with_help),
  };
}
