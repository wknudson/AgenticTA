import React, { useEffect, useMemo, useState } from 'react';
import { CalendarDays, Info, Loader2 } from 'lucide-react';
import MonthCalendar from '../agents/calendar/MonthCalendar';
import {
  type CalendarEvent,
  type Term,
  isWeekend,
  kindLabel,
  longDate,
  monthOf,
  shortDate,
  startingMonth,
  todayISO,
} from '../agents/calendar/calendarUtils';
import { getClassTerm, getPublishedEvents } from '../../services/checkinSettingsApi';

interface Props {
  classId: number;
  /** YYYY-MM-DD, or null when nothing is picked yet. */
  value: string | null;
  onChange: (day: string) => void;
  label?: string;
  /** New check-ins: if the starting value is a day off, move it to the next school day once the
   * calendar loads (a default like "the day after tomorrow" can land on a holiday). */
  moveOffDaysOff?: boolean;
}

/** Why a day can't hold a lesson (weekend, outside the term, holiday), or null for a school day. */
function dayOffReason(day: string, term: Term | null): string | null {
  if (isWeekend(day)) return `${longDate(day)} is a weekend.`;
  if (!term) return null;
  if (day < term.term_start || day > term.term_end) {
    return `${longDate(day)} is outside the term (${shortDate(term.term_start)} to ${shortDate(term.term_end)}).`;
  }
  const holiday = term.holidays.find((h) => h.date === day);
  return holiday ? `${longDate(day)} is a holiday: ${holiday.label}.` : null;
}

const field = 'mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-400';

/**
 * Pick the lesson day on the class calendar: holidays, the term and other due dates are shown,
 * and weekends, holidays and days outside the term can't be picked (a click says why). Without
 * a saved term (or if the scheduler can't be reached) it is a plain date input.
 */
/** The first school day on or after `day` (within 90 days and the term), or null. */
function nextSchoolDay(day: string, term: Term | null): string | null {
  const d = new Date(`${day}T00:00:00Z`);
  for (let i = 0; i < 90; i += 1) {
    const iso = d.toISOString().slice(0, 10);
    if (term && iso > term.term_end) return null;
    if (!dayOffReason(iso, term) && (!term || iso >= term.term_start)) return iso;
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return null;
}

const LessonDayPicker: React.FC<Props> = ({ classId, value, onChange, label = 'Lesson date', moveOffDaysOff = false }) => {
  const [term, setTerm] = useState<Term | null>(null);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [month, setMonth] = useState(() => monthOf(value ?? todayISO()));
  const [refusal, setRefusal] = useState('');
  const labelId = `lesson-day-${classId}-label`;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([
      getClassTerm(classId, controller.signal).catch(() => ({ term: null })),
      getPublishedEvents(classId, controller.signal).catch(() => ({ events: [] as CalendarEvent[] })),
    ]).then(([t, e]) => {
      if (controller.signal.aborted) return;
      setTerm(t.term);
      setEvents(e.events);
      if (moveOffDaysOff && value && dayOffReason(value, t.term)) {
        const next = nextSchoolDay(value, t.term);
        if (next && next !== value) onChange(next);
      }
      setMonth((current) => (value ? monthOf(value) : t.term ? startingMonth(t.term, e.events) : current));
      setLoading(false);
    });
    return () => controller.abort();
    // The starting month only matters on load; `value` changes are followed below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId]);

  // Follow a value set from outside (or a reset) to its month.
  useEffect(() => {
    if (value) setMonth((current) => (current.slice(0, 7) === value.slice(0, 7) ? current : monthOf(value)));
  }, [value]);

  const sameDay = useMemo(() => (value ? events.filter((e) => e.date === value) : []), [events, value]);

  const pick = (day: string) => {
    const reason = dayOffReason(day, term);
    if (reason) {
      setRefusal(`${reason} Pick a school day.`);
      return;
    }
    setRefusal('');
    onChange(day);
  };

  if (loading) {
    return (
      <div className="text-sm font-medium text-gray-700">
        {label}
        <p className="mt-1 text-sm text-gray-500 inline-flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Loading the class calendar…
        </p>
      </div>
    );
  }

  if (!term) {
    const weekend = value && isWeekend(value);
    return (
      <label className="block text-sm font-medium text-gray-700">{label}
        <input type="date" className={field} value={value ?? ''} onChange={(e) => e.target.value && onChange(e.target.value)} />
        <span className={`mt-1 block text-xs ${weekend ? 'text-amber-800' : 'text-gray-500'}`}>
          {weekend ? 'That day is a weekend. ' : ''}
          Save term dates and holidays in the Scheduler to pick from the class calendar.
        </span>
      </label>
    );
  }

  return (
    <div role="group" aria-labelledby={labelId} className="space-y-2">
      <p id={labelId} className="text-sm font-medium text-gray-700 inline-flex items-center gap-1.5">
        <CalendarDays className="w-4 h-4" aria-hidden="true" /> {label}
      </p>
      <div className="rounded-xl border border-gray-200 p-3">
        <MonthCalendar month={month} onMonthChange={setMonth} events={events} term={term}
          selected={value} onSelect={pick} compact />
      </div>
      <div aria-live="polite" className="space-y-1">
        {refusal ? (
          <p className="text-xs text-amber-800 rounded-lg bg-amber-50 border border-amber-200 px-2.5 py-1.5 flex gap-1.5">
            <Info className="w-3.5 h-3.5 shrink-0 mt-px" aria-hidden="true" /> {refusal}
          </p>
        ) : value ? (
          <p className="text-xs text-gray-700">
            Lesson on <strong>{longDate(value)}</strong>
            {sameDay.length > 0 && (
              <span className="text-gray-600">
                {' '}· also that day: {sameDay.map((e) => `${e.title} (${kindLabel(e.kind).toLowerCase()})`).join(', ')}
              </span>
            )}
          </p>
        ) : (
          <p className="text-xs text-gray-500">Pick the class this check-in prepares for.</p>
        )}
      </div>
    </div>
  );
};

export default LessonDayPicker;
