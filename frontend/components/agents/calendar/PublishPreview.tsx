import React, { useEffect, useState } from 'react';
import { agentsFetch } from '../../../services/agentsApi';
import { CalendarEvent, kindLabel, kindStyle, shortDate } from './calendarUtils';

/** Approvals inbox: show what publish_calendar would publish (titles and dates, not just ids). */
const PublishPreview: React.FC<{ classId: number; eventIds: number[] }> = ({ classId, eventIds }) => {
  const [events, setEvents] = useState<CalendarEvent[] | null>(null);
  const idKey = eventIds.join(',');

  useEffect(() => {
    const controller = new AbortController();
    agentsFetch<{ events: CalendarEvent[] }>(`/scheduler/events?class_id=${classId}`, { signal: controller.signal })
      .then((r) => { if (!controller.signal.aborted) setEvents(r.events.filter((e) => eventIds.includes(e.event_id))); })
      .catch(() => { if (!controller.signal.aborted) setEvents([]); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId, idKey]);

  if (events === null) return <p className="mt-3 text-sm text-gray-500">Loading events…</p>;
  const missing = eventIds.length - events.length;
  return (
    <div className="mt-3">
      <p className="text-sm text-gray-700 mb-2">{eventIds.length} event(s) will appear on the student calendar:</p>
      <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">
        {events.map((e) => (
          <li key={e.event_id} className="flex items-center gap-3 px-3 py-2 text-sm">
            <span className={`w-2 h-2 rounded-full shrink-0 ${kindStyle(e.kind).dot}`} />
            <time dateTime={e.date} className="w-32 shrink-0 text-gray-600">{shortDate(e.date)}</time>
            <span className="flex-1 text-gray-900">{e.title}</span>
            <span className="text-xs text-gray-500">{kindLabel(e.kind)}</span>
          </li>
        ))}
      </ul>
      {missing > 0 && <p className="mt-2 text-xs text-amber-700">{missing} event(s) were removed or changed since this was drafted.</p>}
      <p className="mt-2 text-xs text-gray-500">To change a date or title first, edit it on the Scheduler calendar, then approve.</p>
    </div>
  );
};

export default PublishPreview;
