import React, { useEffect, useMemo, useState } from 'react';
import { agentsFetch } from '../../services/agentsApi';
import { API_BASE } from '../../services/api';
import MonthCalendar from './calendar/MonthCalendar';
import { CalendarEvent, Term, kindLabel, kindStyle, longDate, shortDate, startingMonth, todayISO } from './calendar/calendarUtils';

/** Student view: published events only, as a compact month plus what's coming up next. */
export default function StudentCalendar({ classId }: { classId: number }) {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [term, setTerm] = useState<Term | null>(null);
  const [month, setMonth] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    const signal = controller.signal;
    setLoading(true); setError(''); setEvents([]); setSelected(null);
    Promise.all([
      agentsFetch<{ events: CalendarEvent[] }>(`/scheduler/events?class_id=${classId}&status=published`, { signal }),
      agentsFetch<{ term: Term | null }>(`/scheduler/term?class_id=${classId}`, { signal }).catch(() => ({ term: null })),
    ]).then(([e, t]) => {
      if (signal.aborted) return;
      setEvents(e.events); setTerm(t.term); setMonth(startingMonth(t.term, e.events));
    }).catch(() => { if (!signal.aborted) setError('The class calendar is unavailable right now.'); })
      .finally(() => { if (!signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [classId]);

  const today = todayISO();
  const upcoming = useMemo(() => events.filter((e) => e.date >= today).slice(0, 5), [events, today]);
  const list = selected ? events.filter((e) => e.date === selected) : upcoming;
  const holiday = selected ? term?.holidays.find((h) => h.date === selected) : undefined;

  return (
    <section className="bg-white border border-gray-200 rounded-2xl p-5">
      <div className="flex justify-between gap-3 mb-3">
        <h2 className="font-semibold">Class calendar</h2>
        {events.length > 0 && <a className="text-sm underline" href={`${API_BASE}/agents/scheduler/calendar.ics?class_id=${classId}`}>Add to my calendar</a>}
      </div>
      {loading && <p className="text-sm">Loading calendar…</p>}
      {error && <p role="status" className="text-sm text-gray-600">{error}</p>}
      {!loading && !error && (
        <>
          <MonthCalendar compact month={month} onMonthChange={setMonth} events={events} term={term}
            selected={selected} onSelect={(d) => setSelected((s) => (s === d ? null : d))} />
          <div className="mt-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-900">{selected ? longDate(selected) : 'Coming up'}</h3>
              {selected && <button type="button" className="text-xs underline" onClick={() => setSelected(null)}>Show upcoming</button>}
            </div>
            {holiday && <p className="text-sm text-amber-800 mt-1">No school: {holiday.label}</p>}
            {list.length === 0 && !holiday && (
              <p className="text-sm text-gray-600 mt-1">
                {events.length === 0 ? 'Your teacher has not published calendar events yet.' : selected ? 'Nothing scheduled.' : 'Nothing else this term.'}
              </p>
            )}
            <ul className="mt-2 space-y-2">
              {list.map((e) => (
                <li key={e.event_id} className="flex items-start gap-2 text-sm">
                  <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${kindStyle(e.kind).dot}`} />
                  <span>
                    {!selected && <time dateTime={e.date} className="font-medium">{shortDate(e.date)} · </time>}
                    {e.title}
                    <span className="block text-xs text-gray-500">{kindLabel(e.kind)}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </section>
  );
}
