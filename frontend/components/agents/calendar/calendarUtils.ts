/** Shared calendar types and helpers. Dates are plain 'YYYY-MM-DD' strings, handled in UTC so
 * a date never shifts by a day in a different time zone. */

export type EventKind = 'assessment' | 'assignment_due' | 'reading' | 'event';

export interface CalendarEvent {
  event_id: number;
  title: string;
  kind: EventKind | string;
  date: string;
  status: 'proposed' | 'published' | string;
  source?: string | null;
}

export interface Holiday {
  date: string;
  label: string;
}

export interface Term {
  term_start: string;
  term_end: string;
  max_per_day: number;
  holidays: Holiday[];
}

export const KINDS: { value: EventKind; label: string }[] = [
  { value: 'assessment', label: 'Quiz / test' },
  { value: 'assignment_due', label: 'Due date' },
  { value: 'reading', label: 'Reading' },
  { value: 'event', label: 'Class event' },
];

/** Tailwind classes per kind: chip (filled), dot, and the swatch used in the legend. */
export const KIND_STYLE: Record<string, { chip: string; dot: string }> = {
  assessment: { chip: 'bg-red-50 text-red-800 border-red-200', dot: 'bg-red-600' },
  assignment_due: { chip: 'bg-blue-50 text-blue-800 border-blue-200', dot: 'bg-blue-600' },
  reading: { chip: 'bg-emerald-50 text-emerald-800 border-emerald-200', dot: 'bg-emerald-600' },
  event: { chip: 'bg-slate-100 text-slate-800 border-slate-200', dot: 'bg-slate-500' },
};

export const kindLabel = (kind: string) => KINDS.find((k) => k.value === kind)?.label ?? 'Class event';
export const kindStyle = (kind: string) => KIND_STYLE[kind] ?? KIND_STYLE.event;

export const toISO = (d: Date) => d.toISOString().slice(0, 10);

export const parseISO = (s: string) => {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
};

export const todayISO = () => {
  const now = new Date();
  return toISO(new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())));
};

/** First of the month, as 'YYYY-MM-01'. */
export const monthOf = (iso: string) => `${iso.slice(0, 7)}-01`;

export const addMonths = (monthISO: string, n: number) => {
  const d = parseISO(monthISO);
  return toISO(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, 1)));
};

export const monthTitle = (monthISO: string) =>
  parseISO(monthISO).toLocaleDateString(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' });

export const longDate = (iso: string) =>
  parseISO(iso).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', timeZone: 'UTC' });

/** 'Fri, Sep 5' (adds the year when it isn't this year, e.g. last year's assignments). */
export const shortDate = (iso: string) =>
  parseISO(iso).toLocaleDateString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC',
    ...(iso.slice(0, 4) !== todayISO().slice(0, 4) ? { year: 'numeric' } : {}),
  });

/** Every day shown in the month grid: whole weeks, Sunday first. */
export const monthGrid = (monthISO: string): string[] => {
  const first = parseISO(monthISO);
  const start = new Date(first);
  start.setUTCDate(1 - first.getUTCDay());
  const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0));
  const end = new Date(last);
  end.setUTCDate(last.getUTCDate() + (6 - last.getUTCDay()));
  const days: string[] = [];
  for (const d = new Date(start); d <= end; d.setUTCDate(d.getUTCDate() + 1)) days.push(toISO(d));
  return days;
};

export const isWeekend = (iso: string) => {
  const day = parseISO(iso).getUTCDay();
  return day === 0 || day === 6;
};

/** Why nothing can be scheduled on a day (weekend, outside the term, holiday), or null for a school day. */
export const dayOffReason = (day: string, term: Term | null | undefined): string | null => {
  if (isWeekend(day)) return `${longDate(day)} is a weekend.`;
  if (!term?.term_start || !term.term_end) return null;
  if (day < term.term_start || day > term.term_end) {
    return `${longDate(day)} is outside the term (${shortDate(term.term_start)} to ${shortDate(term.term_end)}).`;
  }
  const holiday = term.holidays.find((h) => h.date === day);
  return holiday ? `${longDate(day)} is a day off: ${holiday.label}.` : null;
};

/** The month to open on: today if it's in the term, else the term start, else the first event. */
export const startingMonth = (term: Term | null | undefined, events: CalendarEvent[]) => {
  const today = todayISO();
  if (!term) return monthOf(events[0]?.date ?? today);
  if (today >= term.term_start && today <= term.term_end) return monthOf(today);
  return monthOf(today < term.term_start ? term.term_start : term.term_end);
};
