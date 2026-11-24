import { useCallback, useState } from 'react';
import type { ItemProgress } from '../../../services/checkinApi';

/**
 * "Missed cards come back": a small client-side Leitner queue for one game.
 *
 * - The server keeps the real progress (box 1-3, last_correct); this mirrors its box rule so
 *   the order stays right between saves: a miss goes to box 1, a right answer moves up a box
 *   (a first right answer lands in box 2), box 3 is the top.
 * - After an answer the item is put back `replayGap[box]` cards later (3 / 8 / 20 by default),
 *   so a miss returns 3 cards later.
 * - Unmastered items (latest answer wrong, or never answered) come first: a right answer is
 *   never put back ahead of an item that still needs work.
 */

export const DEFAULT_REPLAY_GAP: Record<number, number> = { 1: 3, 2: 8, 3: 20 };
const MAX_BOX = 3;

export const isMastered = (p?: ItemProgress | null) => !!p && (p.last_correct === 1 || p.last_correct === true);

export function gapFor(replayGap: Record<string, number> | undefined, box: number): number {
  const v = Number(replayGap?.[String(box)]);
  return Number.isFinite(v) && v > 0 ? Math.floor(v) : DEFAULT_REPLAY_GAP[box] ?? 3;
}

interface LocalItem { box: number; mastered: boolean; seen: boolean }
interface QueueState { order: string[]; local: Record<string, LocalItem> }

export function initialState(ids: string[], progressFor: (id: string) => ItemProgress | undefined): QueueState {
  const local: Record<string, LocalItem> = {};
  for (const id of ids) {
    const p = progressFor(id);
    local[id] = { box: Number(p?.box) || 0, mastered: isMastered(p), seen: !!p && Number(p.times_seen) > 0 };
  }
  // Missed before first, then never seen (authored order), then mastered from the lowest box up.
  const missed = ids.filter((id) => !local[id].mastered && local[id].seen);
  const unseen = ids.filter((id) => !local[id].mastered && !local[id].seen);
  const mastered = ids.filter((id) => local[id].mastered).sort((a, b) => local[a].box - local[b].box);
  return { order: [...missed, ...unseen, ...mastered], local };
}

export function requeue(state: QueueState, id: string, correct: boolean, replayGap?: Record<string, number>): QueueState {
  const prev = state.local[id] ?? { box: 0, mastered: false, seen: false };
  const box = correct ? (prev.box <= 0 ? 2 : Math.min(prev.box + 1, MAX_BOX)) : 1;
  const local = { ...state.local, [id]: { box, mastered: correct, seen: true } };
  const rest = state.order.filter((x) => x !== id);
  let at: number;
  if (!correct) {
    at = gapFor(replayGap, 1);
  } else {
    let afterUnmastered = 0;
    rest.forEach((x, i) => { if (!local[x]?.mastered) afterUnmastered = i + 1; });
    at = Math.max(gapFor(replayGap, box), afterUnmastered);
  }
  rest.splice(Math.min(at, rest.length), 0, id);
  return { order: rest, local };
}

export function useReplayQueue(
  ids: string[],
  progressFor: (id: string) => ItemProgress | undefined,
  replayGap?: Record<string, number>,
) {
  const [state, setState] = useState<QueueState>(() => initialState(ids, progressFor));
  const record = useCallback(
    (id: string, correct: boolean) => setState((s) => requeue(s, id, correct, replayGap)),
    [replayGap],
  );
  const masteredCount = ids.reduce((n, id) => n + (state.local[id]?.mastered ? 1 : 0), 0);
  return { order: state.order, record, masteredCount, isItemMastered: (id: string) => !!state.local[id]?.mastered };
}
