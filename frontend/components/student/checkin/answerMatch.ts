/**
 * Forgiving answer check for fill-in-the-blank (no model call per answer):
 * case, extra spaces, punctuation and accents don't matter, a leading "the/a/an" is ignored,
 * accepted alternates count, and small typos pass (edit distance 1 for answers of 5+ letters,
 * 2 for 9+). Numbers must match exactly, so "1945" never passes for "1946".
 */

export function normalizeAnswer(text: string): string {
  return (text || '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')      // accents
    .replace(/['‘’`]/g, '')      // apostrophes join ("cell's" -> "cells")
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')      // other punctuation splits ("cell-membrane" -> "cell membrane")
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^(the|a|an) /, '');
}

/** Optimal string alignment distance (Levenshtein plus adjacent swaps), stops early past `max`. */
export function editDistance(a: string, b: string, max = Infinity): number {
  if (a === b) return 0;
  if (Math.abs(a.length - b.length) > max) return max + 1;
  const rows = a.length + 1;
  const cols = b.length + 1;
  const d: number[][] = Array.from({ length: rows }, (_, i) => {
    const row = new Array<number>(cols).fill(0);
    row[0] = i;
    return row;
  });
  for (let j = 0; j < cols; j++) d[0][j] = j;
  for (let i = 1; i < rows; i++) {
    let rowMin = Infinity;
    for (let j = 1; j < cols; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) v = Math.min(v, d[i - 2][j - 2] + 1);
      d[i][j] = v;
      rowMin = Math.min(rowMin, v);
    }
    if (rowMin > max) return max + 1;
  }
  return d[rows - 1][cols - 1];
}

export const typoAllowance = (normalizedTarget: string) => {
  const len = normalizedTarget.replace(/ /g, '').length;
  return len >= 9 ? 2 : len >= 5 ? 1 : 0;
};

const digits = (s: string) => s.replace(/\D/g, '');

export interface AnswerCheck {
  correct: boolean;
  /** Correct, but only thanks to typo forgiveness (show the real spelling). */
  closeEnough: boolean;
}

export function checkAnswer(given: string, answer: string, alternates: readonly string[] = []): AnswerCheck {
  const g = normalizeAnswer(given);
  if (!g) return { correct: false, closeEnough: false };
  const targets = [answer, ...alternates].map(normalizeAnswer).filter(Boolean);
  if (targets.includes(g)) return { correct: true, closeEnough: false };
  const gNoSpace = g.replace(/ /g, '');
  for (const t of targets) {
    if (gNoSpace === t.replace(/ /g, '')) return { correct: true, closeEnough: false };
    if (digits(t) !== digits(g)) continue;
    const allow = typoAllowance(t);
    if (allow > 0 && editDistance(g, t, allow) <= allow) return { correct: true, closeEnough: true };
  }
  return { correct: false, closeEnough: false };
}
