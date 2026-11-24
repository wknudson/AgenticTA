import React, { useEffect, useRef } from 'react';
import { PartyPopper } from 'lucide-react';
import type { LearningSignals } from '../../../services/checkinApi';
import { card, secondaryBtn } from './ui';

interface Props {
  signals: LearningSignals;
  maxPoints: number;
  lessonDate?: string;
  /** Questions missed first and then fixed. */
  fixedCount: number;
  /** Move focus here (it just happened, rather than on a reload). */
  justCompleted: boolean;
  onReview: () => void;
}

const fmt = (v: number | null | undefined) => (v === null || v === undefined ? null : `${Math.round(v)}%`);

const Tile: React.FC<{ label: string; value: string; note: string; tone: string }> = ({ label, value, note, tone }) => (
  <div className={`rounded-2xl border p-4 ${tone}`}>
    <p className="text-xs font-semibold uppercase tracking-wide opacity-80">{label}</p>
    <p className="mt-1 text-2xl font-extrabold tabular-nums">{value}</p>
    <p className="mt-1 text-xs opacity-80">{note}</p>
  </div>
);

/** Every question correct or fixed: full credit, plus how it went. */
const CheckinComplete: React.FC<Props> = ({ signals, maxPoints, lessonDate, fixedCount, justCompleted, onReview }) => {
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => { if (justCompleted) headingRef.current?.focus(); }, [justCompleted]);

  return (
    <section className={`${card} cta-pop overflow-hidden`} aria-labelledby="checkin-complete-title">
      <div className="bg-gradient-to-br from-green-50 to-white px-5 sm:px-6 pt-6 pb-4 text-center">
        <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-100 text-green-700">
          <PartyPopper className="w-8 h-8" aria-hidden="true" />
        </span>
        <h2
          id="checkin-complete-title"
          ref={headingRef}
          tabIndex={-1}
          className="mt-3 text-2xl font-extrabold text-gray-900 focus:outline-none"
        >
          Check-in complete!
        </h2>
        <p className="mt-1 text-gray-700">
          You worked through every question. That's <strong>full credit: {maxPoints} / {maxPoints} points</strong>.
        </p>
      </div>

      <div className="px-5 sm:px-6 pb-6 space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Tile
            label="First-try accuracy"
            value={fmt(signals.first_try_accuracy) ?? '–'}
            note="What you already knew walking in."
            tone="border-green-200 bg-green-50 text-green-900"
          />
          <Tile
            label="Fixed with help"
            value={fmt(signals.fixed_with_help) ?? 'Nothing to fix'}
            note={
              signals.fixed_with_help === null || fixedCount === 0
                ? 'You got every question right the first time.'
                : `You pushed through ${fixedCount === 1 ? 'the one you missed' : `all ${fixedCount} you missed`}.`
            }
            tone="border-indigo-200 bg-indigo-50 text-indigo-900"
          />
          <Tile
            label="Practice mastery"
            value={fmt(signals.practice_mastery) ?? '–'}
            note="Cards you've mastered in the games."
            tone="border-amber-200 bg-amber-50 text-amber-900"
          />
        </div>

        <div className="rounded-2xl bg-gray-50 border border-gray-100 p-4 text-sm text-gray-700 space-y-2">
          <p>
            <strong>Getting something wrong never lowers your grade.</strong> Your grade comes from working through every
            question, and fixing a miss counts just as much as getting it right the first time.
          </p>
          <p>
            Your answers and questions show your teacher what to go over in class{lessonDate ? ` on ${lessonDate}` : ''}. See you there!
          </p>
        </div>

        <button type="button" className={`${secondaryBtn} w-full sm:w-auto`} onClick={onReview}>
          Look back at my answers
        </button>
      </div>
    </section>
  );
};

export default CheckinComplete;
