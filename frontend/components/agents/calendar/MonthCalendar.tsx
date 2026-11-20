import React, { useMemo } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import {
  CalendarEvent,
  KINDS,
  Term,
  addMonths,
  isWeekend,
  kindStyle,
  longDate,
  monthGrid,
  monthOf,
  monthTitle,
  todayISO,
} from './calendarUtils';

interface Props {
  month: string; // 'YYYY-MM-01'
  onMonthChange: (month: string) => void;
  events: CalendarEvent[];
  term?: Term | null;
  /** Dates with a rule problem (conflict) are outlined in red. */
  problemDates?: Set<string>;
  selected?: string | null;
  onSelect?: (date: string) => void;
  /** Dots instead of titles, for narrow columns (the student sidebar). */
  compact?: boolean;
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MAX_CHIPS = 3;

const MonthCalendar: React.FC<Props> = ({
  month, onMonthChange, events, term, problemDates, selected, onSelect, compact = false,
}) => {
  const days = useMemo(() => monthGrid(month), [month]);
  const byDate = useMemo(() => {
    const map: Record<string, CalendarEvent[]> = {};
    for (const e of events) (map[e.date] ??= []).push(e);
    return map;
  }, [events]);
  const holidays = useMemo(() => Object.fromEntries((term?.holidays ?? []).map((h) => [h.date, h.label])), [term]);
  const today = todayISO();
  const inMonth = (d: string) => d.slice(0, 7) === month.slice(0, 7);
  const inTerm = (d: string) => !term || (d >= term.term_start && d <= term.term_end);

  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-2 mb-3">
        <h3 className="font-semibold text-gray-900" aria-live="polite">{monthTitle(month)}</h3>
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => onMonthChange(monthOf(today))}
            className="px-2.5 py-1 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">Today</button>
          <button type="button" aria-label="Previous month" onClick={() => onMonthChange(addMonths(month, -1))}
            className="p-1.5 rounded-lg hover:bg-gray-100"><ChevronLeft className="w-4 h-4" /></button>
          <button type="button" aria-label="Next month" onClick={() => onMonthChange(addMonths(month, 1))}
            className="p-1.5 rounded-lg hover:bg-gray-100"><ChevronRight className="w-4 h-4" /></button>
        </div>
      </div>

      <div className="grid grid-cols-7 text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
        {WEEKDAYS.map((d) => <div key={d} className="px-1 text-center">{compact ? d[0] : d}</div>)}
      </div>

      <div className="grid grid-cols-7 gap-px bg-gray-200 border border-gray-200 rounded-xl overflow-hidden">
        {days.map((d) => {
          const dayEvents = byDate[d] ?? [];
          const holiday = holidays[d];
          const off = !inMonth(d);
          const quiet = isWeekend(d) || !inTerm(d);
          const conflict = problemDates?.has(d);
          const isSelected = selected === d;
          const marker = term?.term_start === d ? 'First day' : term?.term_end === d ? 'Last day' : null;
          const label = [longDate(d), holiday, marker, dayEvents.length ? `${dayEvents.length} event(s)` : '']
            .filter(Boolean).join(', ');
          return (
            <button
              key={d}
              type="button"
              aria-label={label}
              aria-pressed={isSelected}
              onClick={() => onSelect?.(d)}
              className={[
                'relative flex flex-col items-stretch justify-start text-left focus:outline-none focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-[#ba3638]',
                compact ? 'min-h-[44px] p-1' : 'min-h-[52px] sm:min-h-[92px] p-1 sm:p-1.5',
                holiday ? 'bg-amber-50' : quiet ? 'bg-gray-50' : 'bg-white',
                off ? 'opacity-40' : '',
                onSelect ? 'hover:bg-gray-50 cursor-pointer' : 'cursor-default',
                isSelected ? 'ring-2 ring-inset ring-gray-900 z-[1]' : '',
                conflict && !isSelected ? 'ring-2 ring-inset ring-red-500 z-[1]' : '',
              ].join(' ')}
            >
              <span className={[
                'inline-flex self-start items-center justify-center text-xs w-6 h-6 rounded-full',
                d === today ? 'bg-[#ba3638] text-white font-bold' : quiet ? 'text-gray-400' : 'text-gray-700',
              ].join(' ')}>
                {Number(d.slice(8))}
              </span>
              {!compact && (holiday || marker) && (
                <p className={`hidden sm:block text-[10px] leading-tight font-medium truncate ${holiday ? 'text-amber-800' : 'text-gray-500'}`}>
                  {holiday ?? marker}
                </p>
              )}
              {dayEvents.length > 0 && (
                // Dots always in compact mode, and on phones in full mode (titles don't fit).
                <span className={`flex flex-wrap gap-0.5 mt-0.5 ${compact ? '' : 'sm:hidden'}`}>
                  {dayEvents.slice(0, 4).map((e) => (
                    <span key={e.event_id} className={`w-1.5 h-1.5 rounded-full ${kindStyle(e.kind).dot}`} />
                  ))}
                </span>
              )}
              {!compact && (
                <span className="mt-1 hidden sm:flex flex-col gap-0.5">
                  {dayEvents.slice(0, MAX_CHIPS).map((e) => (
                    <span key={e.event_id} title={`${e.title}${e.status === 'proposed' ? ' (waiting for approval)' : ''}`}
                      className={[
                        'block line-clamp-2 break-words rounded-md border px-1.5 py-0.5 text-[11px] leading-tight',
                        kindStyle(e.kind).chip,
                        e.status === 'proposed' ? 'border-dashed opacity-80 italic' : '',
                      ].join(' ')}>
                      {e.title}
                    </span>
                  ))}
                  {dayEvents.length > MAX_CHIPS && (
                    <span className="text-[11px] text-gray-500 px-1">+{dayEvents.length - MAX_CHIPS} more</span>
                  )}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600" aria-label="Legend">
        {KINDS.map((k) => (
          <li key={k.value} className="flex items-center gap-1.5">
            <span className={`w-2.5 h-2.5 rounded-full ${kindStyle(k.value).dot}`} />{k.label}
          </li>
        ))}
        <li className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-amber-100 border border-amber-300" />No school</li>
        {!compact && events.some((e) => e.status === 'proposed') && (
          <li className="flex items-center gap-1.5"><span className="w-4 h-2.5 rounded-sm border border-dashed border-gray-500" />Waiting for approval</li>
        )}
        {problemDates && problemDates.size > 0 && (
          <li className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm ring-2 ring-red-500" />Conflict</li>
        )}
      </ul>
    </div>
  );
};

export default MonthCalendar;
