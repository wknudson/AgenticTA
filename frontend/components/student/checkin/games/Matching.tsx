import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Check, Shuffle } from 'lucide-react';
import type { ItemProgress, MatchingItem } from '../../../../services/checkinApi';
import { useReplayQueue } from '../useReplayQueue';
import { shuffle } from '../utils';
import { primaryBtn } from '../ui';

interface Props {
  items: MatchingItem[];
  progressFor: (itemId: string) => ItemProgress | undefined;
  replayGap: Record<string, number>;
  onAnswer: (itemId: string, correct: boolean) => void;
}

const ROUND_SIZE = 6;

interface Round { no: number; terms: string[]; defs: string[] }

function makeRound(order: string[], no: number): Round {
  const ids = order.slice(0, ROUND_SIZE);
  const terms = shuffle(ids);
  let defs = shuffle(ids);
  if (ids.length > 1 && defs.every((d, i) => d === terms[i])) defs = [...defs.slice(1), defs[0]];
  return { no, terms, defs };
}

/**
 * Tap a term, then its definition (or the other way round). Works with a mouse, touch or the
 * keyboard: every tile is a button. A right pair marks that card right; a wrong pair counts as a
 * miss for the term's card. Rounds of up to 6 pairs, cards that need work first.
 */
const Matching: React.FC<Props> = ({ items, progressFor, replayGap, onAnswer }) => {
  const ids = useMemo(() => items.map((i) => i.item_id), [items]);
  const byId = useMemo(() => new Map(items.map((i) => [i.item_id, i])), [items]);
  const queue = useReplayQueue(ids, progressFor, replayGap);
  const [round, setRound] = useState<Round>(() => makeRound(queue.order, 1));
  const [matched, setMatched] = useState<Set<string>>(new Set());
  const [missesThisRound, setMissesThisRound] = useState(0);
  const [term, setTerm] = useState<string | null>(null);
  const [def, setDef] = useState<string | null>(null);
  const [wrong, setWrong] = useState<{ term: string; def: string; at: number } | null>(null);
  const [announce, setAnnounce] = useState('');
  const nextRef = useRef<HTMLButtonElement | null>(null);

  const done = round.terms.length > 0 && matched.size === round.terms.length;

  useEffect(() => {
    if (!wrong) return;
    const t = window.setTimeout(() => setWrong(null), 700);
    return () => window.clearTimeout(t);
  }, [wrong]);

  useEffect(() => {
    if (done) nextRef.current?.focus();
  }, [done]);

  if (round.terms.length === 0) return <p className="text-sm text-gray-600">No pairs in this set.</p>;

  const tryPair = (termId: string, defId: string) => {
    const t = byId.get(termId);
    const d = byId.get(defId);
    setTerm(null);
    setDef(null);
    if (termId === defId) {
      onAnswer(termId, true);
      queue.record(termId, true);
      setMatched((m) => new Set(m).add(termId));
      setAnnounce(`Match! ${t?.term}: ${t?.definition}`);
    } else {
      onAnswer(termId, false);
      queue.record(termId, false);
      setMissesThisRound((n) => n + 1);
      setWrong({ term: termId, def: defId, at: Date.now() });
      setAnnounce(`Not a match: ${t?.term} doesn't go with "${d?.definition}". Try again.`);
    }
  };

  const pickTerm = (id: string) => {
    if (matched.has(id)) return;
    if (def) tryPair(id, def);
    else setTerm((cur) => (cur === id ? null : id));
  };
  const pickDef = (id: string) => {
    if (matched.has(id)) return;
    if (term) tryPair(term, id);
    else setDef((cur) => (cur === id ? null : id));
  };

  const nextRound = () => {
    setRound(makeRound(queue.order, round.no + 1));
    setMatched(new Set());
    setMissesThisRound(0);
    setTerm(null);
    setDef(null);
    setAnnounce('New round.');
  };

  const tile = (id: string, selected: boolean, isWrong: boolean) => {
    const isMatched = matched.has(id);
    return [
      'w-full text-left rounded-xl border-2 px-3 py-2.5 text-sm break-words transition-colors duration-150',
      'focus:outline-none focus-visible:ring-4 focus-visible:ring-[#ba3638]/30',
      isMatched
        ? 'border-green-300 bg-green-50 text-green-900 cursor-default'
        : isWrong
          ? 'cta-shake border-red-400 bg-red-50 text-gray-900'
          : selected
            ? 'border-[#ba3638] bg-[#ba3638]/10 text-gray-900'
            : 'border-gray-200 bg-white text-gray-900 hover:border-gray-400',
    ].join(' ');
  };

  const instructions = term
    ? `Now pick the definition for "${byId.get(term)?.term}".`
    : def
      ? 'Now pick the term that goes with that definition.'
      : 'Pick a term, then the definition that goes with it.';

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-gray-600">
        <span className="inline-flex items-center gap-1.5">
          <Shuffle className="w-4 h-4" aria-hidden="true" /> Round {round.no} · {matched.size} of {round.terms.length} matched
        </span>
        <span>{queue.masteredCount} of {ids.length} mastered in this set</span>
      </div>

      {done ? (
        <div className="cta-pop rounded-2xl border border-green-200 bg-green-50 p-5 text-center space-y-3">
          <p className="text-lg font-bold text-green-900">Round complete!</p>
          <p className="text-sm text-green-800">
            {missesThisRound === 0
              ? 'A perfect round, no misses.'
              : `${missesThisRound} ${missesThisRound === 1 ? 'miss' : 'misses'} this round. Those cards will come back soon.`}
          </p>
          <button ref={nextRef} type="button" onClick={nextRound} className={primaryBtn}>Next round</button>
        </div>
      ) : (
        <>
          <p className="text-sm font-medium text-gray-800" id={`match-help-${round.no}`}>{instructions}</p>
          <div className="grid grid-cols-1 sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-4">
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Terms</h4>
              <ul className="flex flex-wrap sm:flex-col gap-2">
                {round.terms.map((id) => (
                  <li key={id} className="max-w-full sm:w-full">
                    <button
                      type="button"
                      className={`${tile(id, term === id, wrong?.term === id)} font-semibold`}
                      aria-pressed={term === id}
                      aria-disabled={matched.has(id)}
                      aria-describedby={`match-help-${round.no}`}
                      onClick={() => pickTerm(id)}
                    >
                      <span className="inline-flex items-center gap-1.5">
                        {matched.has(id) && <Check className="w-4 h-4 shrink-0 text-green-700" aria-hidden="true" />}
                        {byId.get(id)?.term}
                        {matched.has(id) && <span className="sr-only">(matched)</span>}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Definitions</h4>
              <ul className="space-y-2">
                {round.defs.map((id) => (
                  <li key={id}>
                    <button
                      type="button"
                      className={tile(id, def === id, wrong?.def === id)}
                      aria-pressed={def === id}
                      aria-disabled={matched.has(id)}
                      onClick={() => pickDef(id)}
                    >
                      {matched.has(id) && <span className="sr-only">Matched: </span>}
                      {byId.get(id)?.definition}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </>
      )}
      <p className="sr-only" aria-live="polite">{announce}</p>
    </div>
  );
};

export default Matching;
