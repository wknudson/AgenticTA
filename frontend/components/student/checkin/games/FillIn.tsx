import React, { useEffect, useId, useMemo, useRef, useState } from 'react';
import { ArrowRight, Check, X } from 'lucide-react';
import type { FillInItem, ItemProgress } from '../../../../services/checkinApi';
import { useReplayQueue } from '../useReplayQueue';
import { checkAnswer, type AnswerCheck } from '../answerMatch';
import { primaryBtn, textInput } from '../ui';

interface Props {
  items: FillInItem[];
  progressFor: (itemId: string) => ItemProgress | undefined;
  replayGap: Record<string, number>;
  onAnswer: (itemId: string, correct: boolean) => void;
}

const BLANK = /_{2,}/;

/** The sentence with its blank drawn in (and filled once checked). */
const Sentence: React.FC<{ sentence: string; fill: string | null; correct: boolean | null }> = ({ sentence, fill, correct }) => {
  const parts = sentence.split(BLANK);
  const blank = (key: number) => (
    <span
      key={`b${key}`}
      className={`inline-block min-w-[4.5rem] mx-1 px-1 border-b-2 text-center align-baseline ${
        correct === null ? 'border-gray-400' : correct ? 'border-green-600 text-green-800' : 'border-amber-500 text-amber-900'
      }`}
    >
      {fill ?? ' '}
      {fill === null && <span className="sr-only">blank</span>}
    </span>
  );
  if (parts.length === 1) {
    return <>{sentence} {blank(0)}</>;
  }
  return <>{parts.flatMap((p, i) => (i === 0 ? [p] : [blank(i), p]))}</>;
};

/** Type the missing word. Checked in the browser with forgiving matching (see answerMatch.ts). */
const FillIn: React.FC<Props> = ({ items, progressFor, replayGap, onAnswer }) => {
  const ids = useMemo(() => items.map((i) => i.item_id), [items]);
  const byId = useMemo(() => new Map(items.map((i) => [i.item_id, i])), [items]);
  const queue = useReplayQueue(ids, progressFor, replayGap);
  const [shownId, setShownId] = useState<string | undefined>(() => queue.order[0]);
  const [value, setValue] = useState('');
  const [result, setResult] = useState<AnswerCheck | null>(null);
  const [played, setPlayed] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const nextRef = useRef<HTMLButtonElement | null>(null);
  const inputId = useId();
  const feedbackId = useId();

  // Keyboard flow: Enter checks, focus jumps to "Next card", Enter again, back in the input.
  // (Not on first render, so phones don't pop the keyboard open just from opening the game.)
  useEffect(() => {
    if (result) nextRef.current?.focus();
    else if (played > 0) inputRef.current?.focus({ preventScroll: true });
  }, [result, played]);

  const current = shownId ? byId.get(shownId) : undefined;
  if (!current) return <p className="text-sm text-gray-600">No fill-in-the-blank cards in this set.</p>;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (result || !value.trim()) return;
    const r = checkAnswer(value, current.answer, current.alternates ?? []);
    setResult(r);
    onAnswer(current.item_id, r.correct);
    queue.record(current.item_id, r.correct);
  };

  const next = () => {
    setShownId(queue.order[0]);
    setValue('');
    setResult(null);
    setPlayed((n) => n + 1);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-gray-600">
        <span>Card {played + 1}</span>
        <span>{queue.masteredCount} of {ids.length} mastered in this set</span>
      </div>

      <p className="rounded-2xl border-2 border-gray-200 bg-white p-5 text-lg sm:text-xl leading-relaxed text-gray-900 break-words">
        <Sentence
          sentence={current.sentence}
          fill={result ? (result.correct ? value.trim() : current.answer) : null}
          correct={result ? result.correct : null}
        />
      </p>

      <form onSubmit={submit} className="space-y-3">
        <label htmlFor={inputId} className="block text-sm font-medium text-gray-800">Your answer</label>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            ref={inputRef}
            id={inputId}
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            readOnly={!!result}
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            aria-describedby={result ? feedbackId : undefined}
            className={`${textInput} sm:flex-1 ${result ? (result.correct ? 'border-green-500' : 'border-amber-500') : ''}`}
            placeholder="Type the missing word"
          />
          {!result && (
            <button type="submit" disabled={!value.trim()} className={primaryBtn}>Check</button>
          )}
        </div>
      </form>

      <div id={feedbackId} role="status" aria-live="polite">
        {result && (
          <div
            className={`cta-pop rounded-xl border px-4 py-3 text-sm ${
              result.correct ? 'border-green-200 bg-green-50 text-green-900' : 'border-amber-200 bg-amber-50 text-amber-900'
            }`}
          >
            {result.correct ? (
              <p className="flex items-start gap-2">
                <Check className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
                <span>
                  <strong>Correct!</strong>
                  {result.closeEnough && <> Close enough. It's spelled <strong>{current.answer}</strong>.</>}
                </span>
              </p>
            ) : (
              <p className="flex items-start gap-2">
                <X className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" />
                <span>
                  Not quite. The answer is <strong>{current.answer}</strong>. This card will come back soon.
                </span>
              </p>
            )}
          </div>
        )}
      </div>

      {result && (
        <button ref={nextRef} type="button" onClick={next} className={`${primaryBtn} w-full sm:w-auto`}>
          Next card <ArrowRight className="w-4 h-4" aria-hidden="true" />
        </button>
      )}
    </div>
  );
};

export default FillIn;
