import React, { useCallback, useEffect, useRef, useState } from 'react';
import { BookOpen, CalendarDays, Check, CircleAlert, Clock, Lock } from 'lucide-react';
import {
  CheckinApiError,
  getCheckin,
  getPractice,
  type CheckinAssignmentInfo,
  type CheckinQuestion,
  type CheckinState,
  type LearningSignals,
  type PracticeAnswerResult,
  type PracticeState,
  type PracticeStats,
} from '../../../services/checkinApi';
import { COLORS } from '../../../constants';
import Practice from './Practice';
import CheckinQuestions from './CheckinQuestions';
import CheckinComplete from './CheckinComplete';
import UnlockCelebration from './UnlockCelebration';
import { CheckinStyles, Spinner, card, primaryBtn } from './ui';
import { formatDate, pct, useReducedMotion } from './utils';

interface Props {
  /** The check-in as Express returned it (GET /api/student/assignments/:classId/:assignmentId). */
  assignment: CheckinAssignmentInfo;
  token: string;
  loginHref: string;
}

type Step = 1 | 2;

const toStats = (r: PracticeAnswerResult): PracticeStats => ({
  mastered: r.mastered, total: r.total, mastery: r.mastery, threshold: r.threshold, unlocked: r.unlocked,
  level: r.level, levels: r.levels, points: r.points, streak: r.streak, best_streak: r.best_streak,
  answers: r.answers, started: r.started,
});

/**
 * The student's check-in page: step 1 practice games until the mastery bar crosses the
 * teacher's line, then step 2 the check-in (every miss fixed with the tutor = full credit).
 */
const CheckinFlow: React.FC<Props> = ({ assignment, token, loginHref }) => {
  const assignmentId = assignment.assignmentId;
  const [practice, setPractice] = useState<PracticeState | null>(null);
  const [checkin, setCheckin] = useState<CheckinState | null>(null);
  const [stats, setStats] = useState<PracticeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [authError, setAuthError] = useState('');
  const [step, setStep] = useState<Step>(1);
  // Once the check-in is open it stays open for this visit, even if a later miss dips mastery.
  const [everUnlocked, setEverUnlocked] = useState(false);
  const [celebrate, setCelebrate] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [justCompleted, setJustCompleted] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const topRef = useRef<HTMLDivElement | null>(null);
  const reduced = useReducedMotion();

  const onAuthError = useCallback((message: string) => setAuthError(message || 'Your login has expired.'), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError('');
    Promise.all([getPractice(assignmentId, token, controller.signal), getCheckin(assignmentId, token, controller.signal)])
      .then(([p, c]) => {
        if (controller.signal.aborted) return;
        const s = p.stats ?? c.practice;
        const open = !!(s?.unlocked || c.unlocked || (c.signals?.answered ?? 0) > 0);
        setPractice(p);
        setCheckin(c);
        setStats(s);
        setEverUnlocked(open);
        setStep(open ? 2 : 1);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        if (err instanceof CheckinApiError && err.status === 401) onAuthError(err.message);
        setLoadError(err instanceof Error ? err.message : 'Failed to load the check-in.');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [assignmentId, token, reloadKey, onAuthError]);

  /** The questions arrive only once the gate is unlocked, so fetch them again then. */
  const refreshCheckin = useCallback(async () => {
    try {
      const c = await getCheckin(assignmentId, token);
      setCheckin(c);
    } catch (err) {
      if (err instanceof CheckinApiError && err.status === 401) onAuthError(err.message);
    }
  }, [assignmentId, token, onAuthError]);

  const onPracticeResult = useCallback(
    (r: PracticeAnswerResult) => {
      setStats(toStats(r));
      if (r.unlocked) setEverUnlocked(true);
      if (r.just_unlocked) {
        setCelebrate(true);
        void refreshCheckin();
      }
    },
    [refreshCheckin],
  );

  const onQuestion = useCallback((q: CheckinQuestion) => {
    setCheckin((c) => c && { ...c, questions: c.questions.map((x) => (x.question_id === q.question_id ? { ...x, ...q } : x)) });
  }, []);

  const completeRef = useRef(false);
  useEffect(() => { completeRef.current = !!checkin?.signals?.complete; }, [checkin]);

  const onSignals = useCallback((s: LearningSignals) => {
    if (s.complete && !completeRef.current) {
      completeRef.current = true;
      setJustCompleted(true);
      setReviewing(false);
    }
    setCheckin((c) => c && { ...c, signals: s });
  }, []);

  const goTo = (next: Step) => {
    setStep(next);
    setReviewing(false);
    if (next === 2 && checkin && checkin.questions.length === 0) void refreshCheckin();
    topRef.current?.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
  };

  const readOnly = !!(assignment.pastDue || checkin?.assignment?.past_due);
  const unlocked = everUnlocked || !!stats?.unlocked;
  const dueDate = assignment.dueDate ?? checkin?.assignment?.due_date ?? null;
  const lessonDate = assignment.lessonDate ?? checkin?.assignment?.lesson_date ?? null;
  const unit = assignment.unit ?? checkin?.assignment?.unit ?? null;
  const maxPoints = checkin?.assignment?.max_points ?? assignment.maxPoints;
  const signals = checkin?.signals;
  const threshold = stats ? pct(stats.threshold) : pct(assignment.masteryThreshold ?? 0.8);
  const complete = !!signals?.complete;

  return (
    <div ref={topRef} className="space-y-6 scroll-mt-24">
      <CheckinStyles />

      <section className={`${card} p-5 sm:p-6`} aria-labelledby="checkin-title">
        <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: COLORS.primary }}>Before-class check-in</p>
        <h1 id="checkin-title" className="mt-1 text-2xl font-bold text-gray-900 break-words">{assignment.assignmentName}</h1>
        {assignment.description && <p className="mt-2 text-gray-700 break-words">{assignment.description}</p>}

        <dl className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm text-gray-700">
          {unit && (
            <div className="flex items-center gap-1.5 min-w-0">
              <dt><BookOpen className="w-4 h-4 text-gray-500" aria-hidden="true" /><span className="sr-only">Unit</span></dt>
              <dd className="font-medium break-words min-w-0">{unit}</dd>
            </div>
          )}
          {dueDate && (
            <div className="flex items-center gap-1.5">
              <dt><Clock className="w-4 h-4 text-gray-500" aria-hidden="true" /><span className="sr-only">Due</span></dt>
              <dd>
                Due {formatDate(dueDate)}
                {readOnly && (
                  <span className="ml-2 rounded-full bg-gray-200 px-2 py-0.5 text-xs font-semibold text-gray-700">Closed</span>
                )}
              </dd>
            </div>
          )}
          {lessonDate && (
            <div className="flex items-center gap-1.5">
              <dt><CalendarDays className="w-4 h-4 text-gray-500" aria-hidden="true" /><span className="sr-only">Lesson</span></dt>
              <dd>Class on {formatDate(lessonDate, false)}</dd>
            </div>
          )}
        </dl>

        <p className="mt-4 text-sm text-gray-600">
          Practice until the check-in unlocks, then work through every question with the tutor's help.
          You get full credit ({maxPoints} points) for finishing. Mistakes never lower your grade.
        </p>

        <nav aria-label="Check-in steps" className="mt-5">
          <ol className="flex items-center gap-2 sm:gap-3">
            <li className="min-w-0">
              <button
                type="button"
                onClick={() => goTo(1)}
                aria-current={step === 1 ? 'step' : undefined}
                className={`flex w-full items-center gap-2 rounded-xl px-1.5 sm:px-2 py-1.5 text-left transition-colors focus:outline-none focus-visible:ring-4 focus-visible:ring-[#ba3638]/30 ${
                  step === 1 ? 'bg-[#ba3638]/10' : 'hover:bg-gray-50'
                }`}
              >
                <span
                  className={`flex h-7 w-7 sm:h-8 sm:w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                    unlocked ? 'bg-green-600 text-white' : step === 1 ? 'bg-[#ba3638] text-white' : 'bg-gray-200 text-gray-700'
                  }`}
                  aria-hidden="true"
                >
                  {unlocked ? <Check className="w-4 h-4" /> : 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-gray-900">Practice</span>
                  <span className="block text-xs text-gray-600 truncate">{stats ? `${pct(stats.mastery)}% mastered` : 'Games'}</span>
                </span>
              </button>
            </li>
            <li aria-hidden="true" className="flex-1 min-w-[1rem]">
              <div className="h-1 rounded-full bg-gray-200 overflow-hidden">
                <div
                  className="h-full bg-green-600 transition-[width] duration-700 motion-reduce:transition-none"
                  style={{ width: unlocked ? '100%' : `${stats ? Math.min(100, (100 * stats.mastery) / Math.max(stats.threshold, 0.01)) : 0}%` }}
                />
              </div>
            </li>
            <li className="min-w-0">
              <button
                type="button"
                onClick={() => unlocked && goTo(2)}
                disabled={!unlocked}
                aria-current={step === 2 ? 'step' : undefined}
                aria-describedby={!unlocked ? 'step2-locked' : undefined}
                className={`flex w-full items-center gap-2 rounded-xl px-1.5 sm:px-2 py-1.5 text-left transition-colors focus:outline-none focus-visible:ring-4 focus-visible:ring-[#ba3638]/30 disabled:cursor-not-allowed ${
                  step === 2 ? 'bg-[#ba3638]/10' : unlocked ? 'hover:bg-gray-50' : ''
                }`}
              >
                <span
                  className={`flex h-7 w-7 sm:h-8 sm:w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${
                    complete ? 'bg-green-600 text-white' : step === 2 ? 'bg-[#ba3638] text-white' : unlocked ? 'bg-gray-200 text-gray-800' : 'bg-gray-100 text-gray-400'
                  }`}
                  aria-hidden="true"
                >
                  {complete ? <Check className="w-4 h-4" /> : unlocked ? 2 : <Lock className="w-4 h-4" />}
                </span>
                <span className="min-w-0">
                  <span className={`block text-sm font-semibold ${unlocked ? 'text-gray-900' : 'text-gray-500'}`}>Check-in</span>
                  <span id="step2-locked" className="block text-xs text-gray-600 truncate">
                    {!unlocked
                      ? `Unlocks at ${threshold}%`
                      : signals && signals.total > 0
                        ? `${signals.resolved} of ${signals.total} resolved`
                        : 'Unlocked'}
                  </span>
                </span>
              </button>
            </li>
          </ol>
        </nav>
      </section>

      {authError && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <CircleAlert className="w-4 h-4 shrink-0" aria-hidden="true" />
          <span className="flex-1 min-w-0">{authError}</span>
          <a href={loginHref} className="font-semibold underline">Log in again</a>
        </div>
      )}

      {loading ? (
        <section className={`${card} p-6`}>
          <Spinner label="Loading your practice and check-in…" className="text-sm text-gray-600" />
        </section>
      ) : loadError || !practice || !checkin || !stats ? (
        <section className={`${card} p-6 space-y-3`} role="alert">
          <h2 className="font-semibold text-gray-900">We couldn't load this check-in</h2>
          <p className="text-sm text-gray-600">{loadError || 'No data came back from the server.'}</p>
          <button type="button" className={primaryBtn} onClick={() => setReloadKey((k) => k + 1)}>Try again</button>
        </section>
      ) : (
        <>
          {/* Both steps stay mounted (one hidden), so switching keeps game progress and drafts. */}
          <div hidden={step !== 1}>
            <Practice
              assignmentId={assignmentId}
              token={token}
              data={practice}
              stats={stats}
              readOnly={readOnly}
              closedOn={dueDate ? formatDate(dueDate) : undefined}
              onResult={onPracticeResult}
              onAuthError={onAuthError}
            />
          </div>
          {unlocked && (
            <div hidden={step !== 2} className="space-y-3">
              {complete && !reviewing ? (
                <CheckinComplete
                  signals={checkin.signals}
                  maxPoints={maxPoints}
                  lessonDate={lessonDate ? formatDate(lessonDate, false) : undefined}
                  fixedCount={checkin.questions.filter((q) => q.status === 'fixed').length}
                  justCompleted={justCompleted && step === 2}
                  onReview={() => setReviewing(true)}
                />
              ) : (
                <>
                  {complete && (
                    <button type="button" className="text-sm font-semibold underline text-gray-700" onClick={() => setReviewing(false)}>
                      Back to your summary
                    </button>
                  )}
                  <CheckinQuestions
                    key={checkin.questions.length}
                    assignmentId={assignmentId}
                    token={token}
                    state={checkin}
                    readOnly={readOnly}
                    closedOn={dueDate ? formatDate(dueDate) : undefined}
                    onQuestion={onQuestion}
                    onSignals={onSignals}
                    onAuthError={onAuthError}
                    onReload={refreshCheckin}
                  />
                </>
              )}
            </div>
          )}
        </>
      )}

      {celebrate && stats && (
        <UnlockCelebration
          masteryPct={pct(stats.mastery)}
          onStart={() => { setCelebrate(false); goTo(2); }}
          onClose={() => setCelebrate(false)}
        />
      )}
    </div>
  );
};

export default CheckinFlow;
