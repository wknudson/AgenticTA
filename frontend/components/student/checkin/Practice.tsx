import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CircleAlert, Layers, PenLine, Puzzle, Sparkles, type LucideIcon } from 'lucide-react';
import {
  CheckinApiError,
  postPracticeAnswer,
  type GameActivity,
  type GameKind,
  type ItemProgress,
  type PracticeAnswerResult,
  type PracticeState,
  type PracticeStats,
} from '../../../services/checkinApi';
import PracticeStatsBar, { type Reward } from './PracticeStatsBar';
import Flashcards from './games/Flashcards';
import Matching from './games/Matching';
import FillIn from './games/FillIn';
import { isMastered } from './useReplayQueue';
import { multiplierForStreak } from './utils';
import { card } from './ui';

const KINDS: Record<GameKind, { label: string; icon: LucideIcon }> = {
  flashcards: { label: 'Flashcards', icon: Layers },
  matching: { label: 'Matching', icon: Puzzle },
  fill_in: { label: 'Fill in the blank', icon: PenLine },
};

interface Props {
  assignmentId: number;
  token: string;
  data: PracticeState;
  /** Owned by CheckinFlow (the stepper needs `unlocked`). */
  stats: PracticeStats;
  readOnly: boolean;
  closedOn?: string;
  onResult: (result: PracticeAnswerResult) => void;
  onAuthError: (message: string) => void;
}

const Practice: React.FC<Props> = ({ assignmentId, token, data, stats, readOnly, closedOn, onResult, onAuthError }) => {
  // Only known game kinds, and only items with a stable item_id (progress points at it).
  const activities = useMemo(
    () =>
      (data.activities ?? [])
        .filter((a) => a.kind in KINDS && Array.isArray(a.items))
        .map((a) => ({ ...a, items: (a.items as Array<{ item_id?: string }>).filter((i) => i && i.item_id) }) as GameActivity)
        .filter((a) => a.items.length > 0),
    [data.activities],
  );
  const [progress, setProgress] = useState<Record<string, ItemProgress>>(() => data.progress ?? {});
  const progressRef = useRef(progress);
  progressRef.current = progress;

  const masteredIn = useCallback(
    (a: GameActivity) => (a.items as Array<{ item_id: string }>).filter((i) => isMastered(progress[`${a.activity_id}:${i.item_id}`])).length,
    [progress],
  );

  // Start on the first game that still has cards to master.
  const [activeId, setActiveId] = useState<number | null>(() => {
    const open = activities.find(
      (a) => (a.items as Array<{ item_id: string }>).some((i) => !isMastered(data.progress?.[`${a.activity_id}:${i.item_id}`])),
    );
    return (open ?? activities[0])?.activity_id ?? null;
  });
  const active = activities.find((a) => a.activity_id === activeId) ?? activities[0];

  const [multiplier, setMultiplier] = useState(() => multiplierForStreak(stats.streak));
  const [reward, setReward] = useState<Reward | null>(null);
  const [rewardText, setRewardText] = useState('');
  const [levelUp, setLevelUp] = useState<{ level: number; id: number } | null>(null);
  const [saveError, setSaveError] = useState('');
  const chain = useRef<Promise<void>>(Promise.resolve());
  const seq = useRef(0);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;
  const onAuthErrorRef = useRef(onAuthError);
  onAuthErrorRef.current = onAuthError;

  useEffect(() => {
    if (!levelUp) return;
    const t = window.setTimeout(() => setLevelUp(null), 4000);
    return () => window.clearTimeout(t);
  }, [levelUp]);

  /** Save every answer right away, one at a time (the streak depends on the order). */
  const answer = useCallback(
    (activityId: number, itemId: string, correct: boolean) => {
      const key = `${activityId}:${itemId}`;
      setProgress((p) => {
        const prev = p[key];
        const box = correct ? (!prev || !prev.box ? 2 : Math.min(Number(prev.box) + 1, 3)) : 1;
        return {
          ...p,
          [key]: {
            times_seen: (prev?.times_seen ?? 0) + 1,
            times_correct: (prev?.times_correct ?? 0) + (correct ? 1 : 0),
            last_correct: correct ? 1 : 0,
            box,
          },
        };
      });
      chain.current = chain.current.then(async () => {
        try {
          const r = await postPracticeAnswer(assignmentId, token, { activity_id: activityId, item_id: itemId, correct });
          seq.current += 1;
          setSaveError('');
          setMultiplier(r.multiplier || 1);
          setReward({ id: seq.current, points: r.points_awarded ?? 0, multiplier: r.multiplier || 1, correct });
          setRewardText(
            correct
              ? `Correct. Plus ${r.points_awarded ?? 0} points${(r.multiplier || 1) > 1 ? `, ${r.multiplier} times streak bonus` : ''}.`
              : 'Missed. Your streak starts over, your points stay.',
          );
          if (r.level_up) setLevelUp({ level: r.level, id: seq.current });
          onResultRef.current(r);
        } catch (err) {
          if (err instanceof CheckinApiError && err.status === 401) onAuthErrorRef.current(err.message);
          setSaveError(
            err instanceof CheckinApiError && err.status !== 0 && err.status < 500
              ? `Your last answer wasn't saved: ${err.message}`
              : "Your last answer wasn't saved (connection problem). Keep playing; the card will come back.",
          );
        }
      });
    },
    [assignmentId, token],
  );

  const progressFor = useCallback(
    (activityId: number) => (itemId: string) => progressRef.current[`${activityId}:${itemId}`],
    [],
  );

  return (
    <section className={`${card} p-5 sm:p-6 space-y-5`} aria-labelledby="practice-heading">
      <div>
        <h2 id="practice-heading" className="text-xl font-bold text-gray-900">Practice</h2>
        <p className="text-sm text-gray-600 mt-1">
          Play any game. Every right answer earns points, streaks multiply them, and missed cards come back until you get them.
        </p>
      </div>

      <PracticeStatsBar stats={stats} multiplier={multiplier} reward={reward} />
      <p className="sr-only" aria-live="polite">{rewardText}</p>

      {levelUp && (
        <div key={levelUp.id} role="status" className="cta-pop flex items-center gap-3 rounded-2xl border border-indigo-200 bg-indigo-50 px-4 py-3">
          <Sparkles className="w-6 h-6 shrink-0 text-indigo-600" aria-hidden="true" />
          <p className="text-sm text-indigo-900">
            <strong className="text-base">Level up!</strong> You reached level {levelUp.level} of {stats.levels}.
          </p>
        </div>
      )}

      {saveError && (
        <p role="alert" className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          <CircleAlert className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" /> {saveError}
        </p>
      )}

      {activities.length === 0 ? (
        <p className="text-sm text-gray-600">There are no practice games for this unit, so the check-in is open.</p>
      ) : readOnly ? (
        <div className="space-y-2">
          <p className="text-sm text-gray-700">
            This check-in closed{closedOn ? ` on ${closedOn}` : ''}, so the games are put away. Here's how far you got:
          </p>
          <ul className="divide-y divide-gray-100 rounded-xl border border-gray-200">
            {activities.map((a) => (
              <li key={a.activity_id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                <span className="min-w-0 truncate">{a.title || KINDS[a.kind].label}</span>
                <span className="shrink-0 text-gray-600">{masteredIn(a)} of {a.items.length} mastered</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="space-y-4">
          <div role="group" aria-label="Choose a game" className="flex flex-wrap gap-2">
            {activities.map((a) => {
              const Icon = KINDS[a.kind].icon;
              const selected = active?.activity_id === a.activity_id;
              const sameKind = activities.filter((x) => x.kind === a.kind).length > 1;
              return (
                <button
                  key={a.activity_id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setActiveId(a.activity_id)}
                  className={`inline-flex items-center gap-2 rounded-xl border-2 px-3 py-2 text-sm font-semibold transition-colors focus:outline-none focus-visible:ring-4 focus-visible:ring-[#ba3638]/30 ${
                    selected ? 'border-[#ba3638] bg-[#ba3638]/10 text-gray-900' : 'border-gray-200 bg-white text-gray-700 hover:border-gray-400'
                  }`}
                >
                  <Icon className="w-4 h-4" aria-hidden="true" />
                  <span>{sameKind ? a.title || KINDS[a.kind].label : KINDS[a.kind].label}</span>
                  <span className="rounded-full bg-white/80 border border-gray-200 px-1.5 text-xs font-medium text-gray-600">
                    {masteredIn(a)}/{a.items.length}
                  </span>
                </button>
              );
            })}
          </div>

          {active && (
            <div className="rounded-2xl bg-gray-50 border border-gray-100 p-3 sm:p-5">
              {active.title && <h3 className="text-base font-semibold text-gray-900 mb-3 break-words">{active.title}</h3>}
              {active.kind === 'flashcards' && (
                <Flashcards
                  key={active.activity_id}
                  items={active.items}
                  replayGap={data.replay_gap}
                  progressFor={progressFor(active.activity_id)}
                  onAnswer={(itemId, correct) => answer(active.activity_id, itemId, correct)}
                />
              )}
              {active.kind === 'matching' && (
                <Matching
                  key={active.activity_id}
                  items={active.items}
                  replayGap={data.replay_gap}
                  progressFor={progressFor(active.activity_id)}
                  onAnswer={(itemId, correct) => answer(active.activity_id, itemId, correct)}
                />
              )}
              {active.kind === 'fill_in' && (
                <FillIn
                  key={active.activity_id}
                  items={active.items}
                  replayGap={data.replay_gap}
                  progressFor={progressFor(active.activity_id)}
                  onAnswer={(itemId, correct) => answer(active.activity_id, itemId, correct)}
                />
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
};

export default Practice;
