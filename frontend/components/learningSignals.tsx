/**
 * Learning signals: what teachers see instead of the old AI Dependency score
 * (docs/flipped-classroom-plan.md section 6). Shared by TeacherMetrics, AdminGlobalMetrics
 * and TeacherGrades so the labels, colors and explanations stay the same everywhere.
 */
import React from 'react';
import type { WeeklyLearningSignals } from '../services/api';

export type SignalKey = 'practice' | 'firstTryAccuracy' | 'fixedWithHelp' | 'understanding';

/** Display order: the order a student goes through the work. */
export const SIGNAL_KEYS: SignalKey[] = ['practice', 'firstTryAccuracy', 'fixedWithHelp', 'understanding'];

export const SIGNAL_META: Record<
  SignalKey,
  { label: string; short: string; color: string; badge: string; selectedBg: string; help: string }
> = {
  practice: {
    label: 'Practice',
    short: 'Practice',
    color: '#7c3aed',
    badge: 'bg-violet-50 text-violet-700',
    selectedBg: 'bg-violet-50',
    help:
      'How much of the practice games (flashcards, matching, fill in the blank) the student has mastered. Missed cards keep coming back until they get them right.',
  },
  firstTryAccuracy: {
    label: 'First-try accuracy',
    short: 'First try',
    color: '#2563eb',
    badge: 'bg-blue-50 text-blue-700',
    selectedBg: 'bg-blue-50',
    help:
      'Of the check-in questions a student answered, how many they got right on the first try. It shows what they knew before class. It is feedback only and never lowers their grade.',
  },
  fixedWithHelp: {
    label: 'Fixed with help',
    short: 'Fixed with help',
    color: '#d97706',
    badge: 'bg-amber-50 text-amber-800',
    selectedBg: 'bg-amber-50',
    help:
      'Of the questions a student missed, how many they worked out with the tutor. Using the tutor is good here: a high number means they pushed through instead of guessing or giving up.',
  },
  understanding: {
    label: 'Understanding',
    short: 'Understanding',
    color: '#16a34a',
    badge: 'bg-green-50 text-green-700',
    selectedBg: 'bg-green-50',
    help:
      'First-try accuracy, plus half credit for each miss they fixed without the tutor having to explain the answer. Hints are fine; if the tutor had to walk them through it, that question gets no Understanding credit.',
  },
};

/** 0-100 as a whole percent; an em dash when there's no data (never 0). */
export function fmtSignal(v: number | null | undefined): string {
  return v == null || !Number.isFinite(Number(v)) ? '—' : `${Math.round(Number(v))}%`;
}

export function signalValue(s: WeeklyLearningSignals | null | undefined, key: SignalKey): number | null {
  const v = s?.[key];
  return v == null ? null : Number(v);
}

/** The plain-language explanation of every signal, for "Learn more" panels and chart legends. */
export const LearningSignalsExplainer: React.FC<{ compact?: boolean }> = ({ compact = false }) => (
  <div className={compact ? 'grid grid-cols-1 sm:grid-cols-2 gap-3' : 'space-y-3'}>
    {SIGNAL_KEYS.map((key) => (
      <div key={key} className="rounded-xl border border-gray-200 p-3 text-sm text-gray-700">
        <p className="font-semibold text-gray-900 flex items-center gap-2">
          <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: SIGNAL_META[key].color }} />
          {SIGNAL_META[key].label}
        </p>
        <p className="mt-1">{SIGNAL_META[key].help}</p>
        {key === 'understanding' && !compact && (
          <span className="block mt-2 font-mono text-xs bg-gray-100 rounded px-2 py-1">
            Right first try = full credit · Fixed with hints = half credit · Tutor explained it = no credit
          </span>
        )}
      </div>
    ))}
    <p className={`text-xs text-gray-500 ${compact ? 'sm:col-span-2' : ''}`}>
      The check-in grade itself is completion: answering every question and fixing every miss earns full credit.
      Older graded assignments have no practice or check-in data, so those show a dash (—) instead of 0.
    </p>
  </div>
);
