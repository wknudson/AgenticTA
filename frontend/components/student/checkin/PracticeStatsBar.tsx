import React, { useId } from 'react';
import { Flame, LockOpen, Star, Trophy } from 'lucide-react';
import type { PracticeStats } from '../../../services/checkinApi';
import { COLORS } from '../../../constants';
import { pct } from './utils';

/** The last answer's reward, as the server returned it. `id` changes per answer to replay the pop. */
export interface Reward { id: number; points: number; multiplier: number; correct: boolean }

interface Props {
  stats: PracticeStats;
  /** Current streak multiplier (from the last answer, or derived from the streak on load). */
  multiplier: number;
  reward?: Reward | null;
}

/** Mastery bar with the unlock line at the teacher's threshold. */
export const MasteryBar: React.FC<{ stats: PracticeStats; compact?: boolean }> = ({ stats, compact }) => {
  const value = pct(stats.mastery);
  const threshold = pct(stats.threshold);
  const needed = Math.max(0, Math.ceil(stats.threshold * stats.total - 1e-9) - stats.mastered);
  const labelShift = threshold > 80 ? '-100%' : threshold < 20 ? '0%' : '-50%';
  const labelId = useId();
  return (
    <div>
      {!compact && (
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
          <span id={labelId} className="font-semibold text-gray-900">Mastery</span>
          <span className="text-gray-600">
            {stats.mastered} of {stats.total} cards mastered ({value}%)
          </span>
        </div>
      )}
      <div
        className={`relative ${compact ? 'mt-0' : 'mt-2'} h-3 rounded-full bg-gray-100`}
        role="progressbar"
        aria-labelledby={compact ? undefined : labelId}
        aria-label={compact ? 'Practice mastery' : undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
        aria-valuetext={`${value}% mastered. The check-in unlocks at ${threshold}%.`}
      >
        <div
          className="h-full rounded-full transition-[width] duration-700 ease-out motion-reduce:transition-none"
          style={{ width: `${value}%`, backgroundColor: stats.unlocked ? '#16a34a' : COLORS.primary }}
        />
        <div
          className="absolute -top-1 -bottom-1 w-0.5 rounded bg-gray-800"
          style={{ left: `${threshold}%` }}
          aria-hidden="true"
        />
      </div>
      {!compact && (
        <div className="relative h-5 mt-1 text-xs text-gray-600" aria-hidden="true">
          <span className="absolute whitespace-nowrap" style={{ left: `${threshold}%`, transform: `translateX(${labelShift})` }}>
            Unlock at {threshold}%
          </span>
        </div>
      )}
      {!compact && (
        <p className="text-sm mt-1 text-gray-700">
          {stats.unlocked ? (
            <span className="inline-flex items-center gap-1.5 font-medium text-green-700">
              <LockOpen className="w-4 h-4" aria-hidden="true" /> Check-in unlocked. Keep playing for points any time.
            </span>
          ) : (
            <>Master {needed} more {needed === 1 ? 'card' : 'cards'} to unlock the check-in.</>
          )}
        </p>
      )}
    </div>
  );
};

const PracticeStatsBar: React.FC<Props> = ({ stats, multiplier, reward }) => {
  const levels = Math.max(1, stats.levels || 1);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        <div className="relative rounded-xl bg-amber-50 border border-amber-100 px-3 py-2">
          <div className="flex items-center gap-1.5 text-xs font-medium text-amber-800">
            <Star className="w-3.5 h-3.5" aria-hidden="true" /> Points
          </div>
          <p className="text-xl font-extrabold tabular-nums text-gray-900">{stats.points}</p>
          {reward && reward.correct && reward.points > 0 && (
            <span key={reward.id} className="cta-float absolute right-2 top-1 text-sm font-bold text-amber-700" aria-hidden="true">
              +{reward.points}
            </span>
          )}
        </div>
        <div className="relative rounded-xl bg-orange-50 border border-orange-100 px-3 py-2">
          <div className="flex items-center gap-1.5 text-xs font-medium text-orange-800">
            <Flame className="w-3.5 h-3.5" aria-hidden="true" /> Streak
          </div>
          <div className="flex items-center gap-1.5">
            <p className="text-xl font-extrabold tabular-nums text-gray-900">{stats.streak}</p>
            {multiplier > 1 && (
              <span
                key={`m${multiplier}`}
                className={`cta-pop rounded-full px-1.5 py-0.5 text-xs font-bold text-white ${multiplier >= 3 ? 'bg-red-600' : 'bg-orange-500'}`}
                title={multiplier >= 3 ? '10 in a row: triple points' : '5 in a row: double points'}
              >
                x{multiplier}
              </span>
            )}
          </div>
        </div>
        <div className="rounded-xl bg-indigo-50 border border-indigo-100 px-3 py-2">
          <div className="flex items-center gap-1.5 text-xs font-medium text-indigo-800">
            <Trophy className="w-3.5 h-3.5" aria-hidden="true" /> Level
          </div>
          <p className="text-xl font-extrabold tabular-nums text-gray-900">
            {stats.level}
            <span className="text-sm font-semibold text-gray-500">/{levels}</span>
          </p>
          <div className="flex gap-0.5 mt-0.5" aria-hidden="true">
            {Array.from({ length: levels }, (_, i) => (
              <span key={i} className={`h-1 flex-1 rounded-full ${i < stats.level ? 'bg-indigo-500' : 'bg-indigo-100'}`} />
            ))}
          </div>
        </div>
      </div>
      <MasteryBar stats={stats} />
      {stats.best_streak > 0 && (
        <p className="text-xs text-gray-500">
          Best streak: {stats.best_streak}. Five in a row doubles your points, ten triples them.
        </p>
      )}
    </div>
  );
};

export default PracticeStatsBar;
