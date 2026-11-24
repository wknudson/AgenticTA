import { useEffect, useState } from 'react';

/** Parse "YYYY-MM-DD" as a local date (no UTC shift) and anything else with Date. */
function parseDate(raw: string | null | undefined): { date: Date; hasTime: boolean } | null {
  if (!raw) return null;
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw.trim());
  if (dateOnly) {
    return { date: new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3])), hasTime: false };
  }
  const d = new Date(raw.includes('T') ? raw : raw.replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? null : { date: d, hasTime: true };
}

/** "Mon, Dec 1" (+ ", 11:59 PM" when the value has a time). */
export function formatDate(raw: string | null | undefined, withTime = true): string {
  const p = parseDate(raw);
  if (!p) return raw || '';
  const day = p.date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  if (!withTime || !p.hasTime) return day;
  return `${day}, ${p.date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`;
}

export const pct = (value01: number) => Math.round(Math.max(0, Math.min(1, value01)) * 100);

/** Display only: the server computes points. Same thresholds as the server (x2 at 5, x3 at 10). */
export const multiplierForStreak = (streak: number) => (streak >= 10 ? 3 : streak >= 5 ? 2 : 1);

/** True when the student asked the OS for less motion. */
export function useReducedMotion(): boolean {
  const query = '(prefers-reduced-motion: reduce)';
  const [reduced, setReduced] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia(query);
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener?.('change', onChange);
    return () => mq.removeEventListener?.('change', onChange);
  }, []);
  return reduced;
}

/** Fisher-Yates, returns a copy. */
export function shuffle<T>(arr: readonly T[]): T[] {
  const copy = [...arr];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}
