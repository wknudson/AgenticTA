import React, { useEffect, useState } from 'react';
import { agentsFetch } from '../../services/agentsApi';
import { API_BASE } from '../../services/api';

type Event = { event_id: number; title: string; date: string };

export default function StudentCalendar({ classId }: { classId: number }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setEvents([]);
    agentsFetch<{ events: Event[] }>(`/scheduler/events?class_id=${classId}&status=published`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setEvents(result.events); })
      .catch(() => { if (!controller.signal.aborted) setError('The class calendar is unavailable right now.'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [classId]);
  return <section className="bg-white border border-gray-200 rounded-2xl p-6">
    <div className="flex justify-between gap-3"><h2 className="font-semibold">Class calendar</h2>
      {events.length > 0 && <a className="text-sm underline" href={`${API_BASE}/agents/scheduler/calendar.ics?class_id=${classId}`}>Download calendar</a>}
    </div>
    {loading && <p className="text-sm mt-3">Loading calendar…</p>}
    {error && <p role="status" className="text-sm mt-3 text-gray-600">{error}</p>}
    {!loading && !error && events.length === 0 && <p className="text-sm text-gray-600 mt-3">Your teacher has not published calendar events yet.</p>}
    <ul className="divide-y mt-3">{events.map(event => <li key={event.event_id} className="py-2 text-sm"><time dateTime={event.date} className="font-medium">{event.date}</time> · {event.title}</li>)}</ul>
  </section>;
}
