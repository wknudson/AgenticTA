import React, { useEffect, useId, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, CircleAlert, MessageCircle, Wrench } from 'lucide-react';
import {
  CheckinApiError,
  postCheckinAnswer,
  postCheckinFix,
  type CheckinQuestion,
  type CheckinState,
  type LearningSignals,
  type QuestionStatus,
} from '../../../services/checkinApi';
import TutorPanel from './TutorPanel';
import FixItForm from './FixItForm';
import { Spinner, card, primaryBtn, secondaryBtn, textInput } from './ui';

export const STATUS: Record<QuestionStatus, { label: string; nav: string; dot: string }> = {
  unanswered: { label: 'Not answered yet', nav: 'border-gray-300 bg-white text-gray-700', dot: 'bg-gray-300' },
  correct: { label: 'Correct', nav: 'border-green-600 bg-green-600 text-white', dot: 'bg-green-600' },
  needs_fix: { label: 'Needs a fix', nav: 'border-amber-500 bg-amber-50 text-amber-900', dot: 'bg-amber-500' },
  fixed: { label: 'Fixed', nav: 'border-indigo-500 bg-indigo-50 text-indigo-900', dot: 'bg-indigo-500' },
};

const resolved = (q: CheckinQuestion) => q.status === 'correct' || q.status === 'fixed';

/** first_answer is the text the student gave (for a choice, the option's text). Don't map
 * digits to option ids: an option whose text is "42" would show as a different option. */
const answerText = (q: CheckinQuestion) => q.first_answer ?? '';

interface Props {
  assignmentId: number;
  token: string;
  state: CheckinState;
  readOnly: boolean;
  closedOn?: string;
  onQuestion: (q: CheckinQuestion) => void;
  onSignals: (s: LearningSignals) => void;
  onAuthError: (message: string) => void;
  /** Fetch the check-in again (its questions arrive once the practice gate unlocks). */
  onReload: () => Promise<void> | void;
}

const CheckinQuestions: React.FC<Props> = ({ assignmentId, token, state, readOnly, closedOn, onQuestion, onSignals, onAuthError, onReload }) => {
  const questions = state.questions;
  const signals = state.signals;
  const [idx, setIdx] = useState(() => {
    const open = questions.findIndex((q) => !resolved(q));
    return open >= 0 ? open : 0;
  });
  const [choice, setChoice] = useState<Record<number, number>>({});
  const [text, setText] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<null | 'answer' | 'fix'>(null);
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [answerFeedback, setAnswerFeedback] = useState<Record<number, string | null>>({});
  const [tutorOpen, setTutorOpen] = useState<Record<number, boolean>>({});
  const [focusTick, setFocusTick] = useState(0);
  const resultRef = useRef<HTMLHeadingElement | null>(null);
  const baseId = useId();

  useEffect(() => {
    if (focusTick > 0) resultRef.current?.focus();
  }, [focusTick]);

  const q = questions[Math.min(idx, questions.length - 1)];
  if (!q) {
    return (
      <section className={`${card} p-5 sm:p-6 space-y-3`}>
        <p className="text-sm text-gray-600">
          {readOnly ? 'This check-in closed before its questions were unlocked.' : "The check-in questions aren't ready yet."}
        </p>
        {!readOnly && (
          <button type="button" className={secondaryBtn} onClick={() => void onReload()}>Check again</button>
        )}
      </section>
    );
  }

  const fail = (qid: number, err: unknown) => {
    if (err instanceof CheckinApiError && err.status === 401) onAuthError(err.message);
    // Out of date (e.g. answered in another tab): pull the current state.
    if (err instanceof CheckinApiError && err.status === 409) void onReload();
    setErrors((e) => ({ ...e, [qid]: err instanceof Error ? err.message : 'Something went wrong. Try again.' }));
  };

  const submitAnswer = async () => {
    const isChoice = q.kind === 'choice';
    const body = isChoice
      ? { question_id: q.question_id, option_id: choice[q.question_id] }
      : { question_id: q.question_id, text: (text[q.question_id] ?? '').trim() };
    if (isChoice ? body.option_id === undefined : !body.text) return;
    setBusy('answer');
    setErrors((e) => ({ ...e, [q.question_id]: '' }));
    try {
      const r = await postCheckinAnswer(assignmentId, token, body);
      onQuestion(r.question);
      onSignals(r.signals);
      setAnswerFeedback((f) => ({ ...f, [q.question_id]: r.feedback ?? null }));
      if (!r.correct) setTutorOpen((t) => ({ ...t, [q.question_id]: true }));
      setFocusTick((n) => n + 1);
    } catch (err) {
      fail(q.question_id, err);
    } finally {
      setBusy(null);
    }
  };

  const submitFix = async (body: { option_id?: number; explanation: string }) => {
    setBusy('fix');
    setErrors((e) => ({ ...e, [q.question_id]: '' }));
    try {
      const r = await postCheckinFix(assignmentId, token, { question_id: q.question_id, ...body });
      // Show the judge's words even if the returned question doesn't carry them.
      onQuestion(r.accepted ? r.question : { ...r.question, last_feedback: r.question.last_feedback ?? r.feedback ?? null });
      onSignals(r.signals);
      if (r.accepted) setFocusTick((n) => n + 1);
    } catch (err) {
      fail(q.question_id, err);
    } finally {
      setBusy(null);
    }
  };

  const total = signals?.total || questions.length;
  const done = signals?.resolved ?? questions.filter(resolved).length;
  const showTutor =
    !readOnly && (q.status === 'needs_fix' || (q.status === 'unanswered' && tutorOpen[q.question_id]));
  const error = errors[q.question_id] ?? '';
  const feedback = answerFeedback[q.question_id];
  const after = questions.findIndex((x, i) => i > idx && !resolved(x));
  const nextOpen = after >= 0 ? after : questions.findIndex((x, i) => i !== idx && !resolved(x));

  return (
    <section className={`${card} p-5 sm:p-6 space-y-5`} aria-labelledby={`${baseId}-heading`}>
      <div className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id={`${baseId}-heading`} className="text-xl font-bold text-gray-900">Check-in</h2>
          <p className="text-sm font-semibold text-gray-800" aria-live="polite">{done} of {total} resolved</p>
        </div>
        <div
          className="h-2 rounded-full bg-gray-100"
          role="progressbar"
          aria-label="Questions resolved"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={done}
        >
          <div
            className="h-full rounded-full bg-green-600 transition-[width] duration-500 motion-reduce:transition-none"
            style={{ width: `${total ? (100 * done) / total : 0}%` }}
          />
        </div>
        {readOnly && (
          <p className="rounded-xl bg-gray-100 px-3 py-2 text-sm text-gray-700">
            This check-in closed{closedOn ? ` on ${closedOn}` : ''}. You can look back at your answers, but not change them.
            {total > 0 && (
              <>
                {' '}Your grade: {Math.round(((state.assignment.max_points || 0) * done) / total * 10) / 10} of{' '}
                {state.assignment.max_points} points, for the {done} of {total} questions you resolved.
              </>
            )}
          </p>
        )}
      </div>

      <nav aria-label="Questions">
        <ol className="flex flex-wrap gap-2">
          {questions.map((x, i) => (
            <li key={x.question_id}>
              <button
                type="button"
                onClick={() => setIdx(i)}
                aria-current={i === idx ? 'step' : undefined}
                aria-label={`Question ${x.number}: ${STATUS[x.status].label}`}
                className={`relative flex h-10 w-10 items-center justify-center rounded-full border-2 text-sm font-bold transition-colors focus:outline-none focus-visible:ring-4 focus-visible:ring-[#ba3638]/30 ${
                  STATUS[x.status].nav
                } ${i === idx ? 'ring-2 ring-offset-2 ring-gray-900' : ''}`}
              >
                {x.status === 'correct' ? <Check className="w-4 h-4" aria-hidden="true" /> : x.number}
                {x.status !== 'correct' && (
                  <span className={`absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full border-2 border-white ${STATUS[x.status].dot}`} aria-hidden="true" />
                )}
              </button>
            </li>
          ))}
        </ol>
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600" aria-label="Key">
          {(Object.keys(STATUS) as QuestionStatus[]).map((s) => (
            <li key={s} className="inline-flex items-center gap-1.5">
              <span className={`h-2.5 w-2.5 rounded-full ${STATUS[s].dot}`} aria-hidden="true" /> {STATUS[s].label}
            </li>
          ))}
        </ul>
      </nav>

      <article key={q.question_id} aria-labelledby={`${baseId}-q`} className="space-y-4">
        <div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-semibold uppercase tracking-wide text-gray-500">Question {q.number} of {questions.length}</span>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 font-medium text-gray-700">
              {q.kind === 'choice' ? 'Multiple choice' : 'Explain why'}
            </span>
          </div>
          <h3 id={`${baseId}-q`} className="mt-2 text-lg font-semibold text-gray-900 whitespace-pre-wrap break-words">{q.text}</h3>
        </div>

        {/* ---- Unanswered ---- */}
        {q.status === 'unanswered' && readOnly && (
          <p className="text-sm text-gray-600">You didn't answer this one before the check-in closed.</p>
        )}
        {q.status === 'unanswered' && !readOnly && (
          <form
            className="space-y-3"
            onSubmit={(e) => { e.preventDefault(); void submitAnswer(); }}
          >
            {q.kind === 'choice' ? (
              <fieldset className="space-y-2">
                <legend className="sr-only">Choose an answer</legend>
                {(q.options ?? []).map((o) => {
                  const checked = choice[q.question_id] === o.option_id;
                  return (
                    <label
                      key={o.option_id}
                      className={`flex items-start gap-3 rounded-xl border-2 px-3 py-3 text-sm sm:text-base cursor-pointer transition-colors focus-within:ring-4 focus-within:ring-[#ba3638]/20 ${
                        checked ? 'border-[#ba3638] bg-[#ba3638]/5' : 'border-gray-200 hover:border-gray-400'
                      }`}
                    >
                      <input
                        type="radio"
                        name={`${baseId}-answer-${q.question_id}`}
                        className="mt-1 accent-[#ba3638]"
                        checked={checked}
                        onChange={() => setChoice((c) => ({ ...c, [q.question_id]: o.option_id }))}
                        disabled={busy !== null}
                      />
                      <span className="min-w-0 break-words">{o.text}</span>
                    </label>
                  );
                })}
              </fieldset>
            ) : (
              <div>
                <label htmlFor={`${baseId}-text-${q.question_id}`} className="block text-sm font-medium text-gray-800">
                  Your answer
                </label>
                <p id={`${baseId}-texthelp`} className="text-xs text-gray-500 mb-1.5">Explain why, in your own words. A few sentences is plenty.</p>
                <textarea
                  id={`${baseId}-text-${q.question_id}`}
                  rows={4}
                  maxLength={2000}
                  value={text[q.question_id] ?? ''}
                  onChange={(e) => setText((t) => ({ ...t, [q.question_id]: e.target.value }))}
                  disabled={busy !== null}
                  aria-describedby={`${baseId}-texthelp`}
                  aria-invalid={!!error}
                  className={textInput}
                />
              </div>
            )}

            {error && (
              <p role="alert" className="flex items-start gap-2 text-sm text-red-700">
                <CircleAlert className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" /> {error}
              </p>
            )}

            <div className="flex flex-col-reverse sm:flex-row gap-2">
              <button
                type="button"
                className={secondaryBtn}
                aria-expanded={!!tutorOpen[q.question_id]}
                onClick={() => setTutorOpen((t) => ({ ...t, [q.question_id]: !t[q.question_id] }))}
              >
                <MessageCircle className="w-4 h-4" aria-hidden="true" />
                {tutorOpen[q.question_id] ? 'Hide the tutor' : 'Ask the tutor'}
              </button>
              <button
                type="submit"
                className={`${primaryBtn} sm:ml-auto`}
                disabled={
                  busy !== null ||
                  (q.kind === 'choice' ? choice[q.question_id] === undefined : !(text[q.question_id] ?? '').trim())
                }
              >
                {busy === 'answer' ? <Spinner label="Checking…" /> : 'Submit answer'}
              </button>
            </div>
          </form>
        )}

        {/* ---- Result banners ---- */}
        <div role="status" aria-live="polite">
          {q.status === 'correct' && (
            <div className="cta-pop rounded-2xl border border-green-200 bg-green-50 p-4 space-y-1">
              <h4 ref={resultRef} tabIndex={-1} className="flex items-center gap-2 font-bold text-green-900 focus:outline-none">
                <Check className="w-5 h-5" aria-hidden="true" /> Right on the first try!
              </h4>
              {q.first_answer && <p className="text-sm text-green-900 break-words">Your answer: {answerText(q)}</p>}
              {feedback && <p className="text-sm text-green-800 break-words">{feedback}</p>}
            </div>
          )}
          {q.status === 'needs_fix' && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 space-y-1">
              <h4 ref={resultRef} tabIndex={-1} className="flex items-center gap-2 font-bold text-amber-900 focus:outline-none">
                <CircleAlert className="w-5 h-5" aria-hidden="true" /> Not quite, and that's okay.
              </h4>
              {q.first_answer && <p className="text-sm text-amber-900 break-words">Your first answer: {answerText(q)}</p>}
              {feedback && <p className="text-sm text-amber-900 break-words">{feedback}</p>}
              {!readOnly && (
                <p className="text-sm text-amber-900">
                  Talk it through with the tutor, then fix it below. Fixing it counts just as much as getting it right the first time.
                </p>
              )}
            </div>
          )}
          {q.status === 'fixed' && (
            <div className="cta-pop rounded-2xl border border-indigo-200 bg-indigo-50 p-4 space-y-1">
              <h4 ref={resultRef} tabIndex={-1} className="flex items-center gap-2 font-bold text-indigo-900 focus:outline-none">
                <Wrench className="w-5 h-5" aria-hidden="true" /> Fixed! You worked it out.
              </h4>
              <p className="text-sm text-indigo-900">
                {q.help_level === 'explained'
                  ? 'The tutor walked you through it, and you explained it back in your own words.'
                  : q.help_level === 'hint'
                    ? 'You fixed it with a hint from the tutor.'
                    : 'You fixed it on your own.'}
              </p>
              {q.first_answer && <p className="text-sm text-indigo-900/80 break-words">Your first answer was: {answerText(q)}</p>}
            </div>
          )}
        </div>

        {showTutor && (
          <TutorPanel
            key={`tutor-${q.question_id}`}
            assignmentId={assignmentId}
            token={token}
            question={q}
            tutorMode={state.assignment.tutor_mode}
            revealAfter={state.assignment.tutor_reveal_after || 2}
            readOnly={readOnly}
            onQuestion={onQuestion}
            onAuthError={onAuthError}
          />
        )}

        {q.status === 'needs_fix' && !readOnly && (
          <FixItForm key={`fix-${q.question_id}`} question={q} busy={busy === 'fix'} error={error} onSubmit={(b) => void submitFix(b)} />
        )}
      </article>

      <div className="flex items-center justify-between gap-2 border-t border-gray-100 pt-4">
        <button type="button" className={secondaryBtn} disabled={idx === 0} onClick={() => setIdx((i) => Math.max(0, i - 1))}>
          <ArrowLeft className="w-4 h-4" aria-hidden="true" /> <span className="hidden sm:inline">Previous</span>
          <span className="sr-only sm:hidden">Previous question</span>
        </button>
        {resolved(q) && nextOpen >= 0 ? (
          <button type="button" className={primaryBtn} onClick={() => setIdx(nextOpen)}>
            Next open question <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </button>
        ) : (
          <button
            type="button"
            className={secondaryBtn}
            disabled={idx >= questions.length - 1}
            onClick={() => setIdx((i) => Math.min(questions.length - 1, i + 1))}
          >
            <span className="hidden sm:inline">Next</span>
            <span className="sr-only sm:hidden">Next question</span> <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </button>
        )}
      </div>
    </section>
  );
};

export default CheckinQuestions;
