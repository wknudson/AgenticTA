import React, { useMemo, useRef, useState } from 'react';
import { Check, RotateCcw } from 'lucide-react';
import type { FlashcardItem, ItemProgress } from '../../../../services/checkinApi';
import { useReplayQueue } from '../useReplayQueue';
import { useReducedMotion } from '../utils';
import { secondaryBtn, successBtn } from '../ui';

interface Props {
  items: FlashcardItem[];
  progressFor: (itemId: string) => ItemProgress | undefined;
  replayGap: Record<string, number>;
  onAnswer: (itemId: string, correct: boolean) => void;
}

/** Flip the card, then say honestly whether you knew it. "Not yet" brings the card back soon. */
const Flashcards: React.FC<Props> = ({ items, progressFor, replayGap, onAnswer }) => {
  const ids = useMemo(() => items.map((i) => i.item_id), [items]);
  const byId = useMemo(() => new Map(items.map((i) => [i.item_id, i])), [items]);
  const queue = useReplayQueue(ids, progressFor, replayGap);
  const reduced = useReducedMotion();
  const [flipped, setFlipped] = useState(false);
  const [played, setPlayed] = useState(0);
  const [note, setNote] = useState('');
  const cardRef = useRef<HTMLButtonElement | null>(null);

  const current = byId.get(queue.order[0]);
  if (!current) return <p className="text-sm text-gray-600">No flashcards in this set.</p>;

  const answer = (correct: boolean) => {
    if (!flipped) return;
    onAnswer(current.item_id, correct);
    queue.record(current.item_id, correct);
    setFlipped(false);
    setPlayed((n) => n + 1);
    setNote(correct ? 'Nice! Next card.' : 'No problem. That card will come back in a few cards.');
    requestAnimationFrame(() => cardRef.current?.focus());
  };

  const allMastered = queue.masteredCount === ids.length;
  const face = 'col-start-1 row-start-1 flex flex-col rounded-2xl border-2 p-5 sm:p-6 min-h-[13rem] sm:min-h-[15rem]';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-gray-600">
        <span>Card {played + 1}</span>
        <span>{queue.masteredCount} of {ids.length} mastered in this set</span>
      </div>

      {allMastered && (
        <p className="rounded-xl bg-green-50 border border-green-200 px-3 py-2 text-sm text-green-800">
          Every card in this set is mastered. Keep going for points, or try another game.
        </p>
      )}

      <div className="[perspective:1200px]">
        <button
          ref={cardRef}
          type="button"
          onClick={() => setFlipped((f) => !f)}
          aria-label={flipped ? `Answer: ${current.back}. Press to see the front again.` : `${current.front}. Press to flip the card.`}
          className="block w-full text-left rounded-2xl focus:outline-none focus-visible:ring-4 focus-visible:ring-[#ba3638]/30"
        >
          {/* A new key per card, so the next card never animates in showing its answer. */}
          <div
            key={`${current.item_id}-${played}`}
            className={`grid ${reduced ? '' : 'transition-transform duration-500 ease-out [transform-style:preserve-3d]'} ${
              flipped && !reduced ? '[transform:rotateY(180deg)]' : ''
            }`}
          >
            <div
              aria-hidden="true"
              className={`${face} border-gray-200 bg-white shadow-sm ${reduced ? (flipped ? 'invisible' : '') : '[backface-visibility:hidden]'}`}
            >
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Front</span>
              <span className="flex-1 flex items-center justify-center text-center text-xl sm:text-2xl font-bold text-gray-900 break-words py-4">
                {current.front}
              </span>
              <span className="text-xs text-gray-500 text-center">Tap the card or press Space to flip</span>
            </div>
            <div
              aria-hidden="true"
              className={`${face} border-[#ba3638]/30 bg-[#ba3638]/5 ${
                reduced ? (flipped ? '' : 'invisible') : '[backface-visibility:hidden] [transform:rotateY(180deg)]'
              }`}
            >
              <span className="text-xs font-semibold uppercase tracking-wide text-[#ba3638]">Answer</span>
              <span className="flex-1 flex items-center justify-center text-center text-lg sm:text-xl font-semibold text-gray-900 break-words py-4">
                {current.back}
              </span>
              <span className="text-xs text-gray-500 text-center">Did you know it?</span>
            </div>
          </div>
        </button>
      </div>

      <p className="sr-only" aria-live="polite">{flipped ? `Answer: ${current.back}` : note}</p>

      {flipped ? (
        <div className="grid grid-cols-2 gap-3">
          <button type="button" onClick={() => answer(false)} className={secondaryBtn}>
            <RotateCcw className="w-4 h-4" aria-hidden="true" /> Not yet
          </button>
          <button type="button" onClick={() => answer(true)} className={successBtn}>
            <Check className="w-4 h-4" aria-hidden="true" /> Got it
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => { setFlipped(true); requestAnimationFrame(() => cardRef.current?.focus()); }}
          className={`${secondaryBtn} w-full`}
        >
          Show the answer
        </button>
      )}
      <p className="text-xs text-gray-500" aria-hidden="true">{note}</p>
    </div>
  );
};

export default Flashcards;
