import React, { useCallback, useEffect, useState } from 'react';
import { agentsFetch } from '../../services/agentsApi';
import AgentPanelShell from './AgentPanelShell';
import type { AgentPanelProps } from './registry';

/**
 * Scheduler.  Owner: Teammate B.
 * TODO(Teammate B): term dates + holidays form (term_calendar), a real calendar grid with
 * conflict flags, a "Build calendar" button calling POST /agents/scheduler/run, the
 * student calendar view (status=published), and an optional .ics download.
 */
interface CalendarEvent {
  event_id: number;
  title: string;
  kind: string;
  date: string;
  status: string;
}

const SchedulerPanel: React.FC<AgentPanelProps> = ({ classId }) => {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const load = useCallback(() => {
    agentsFetch<{ events: CalendarEvent[] }>(`/scheduler/events?class_id=${classId}`).then((r) => setEvents(r.events)).catch(() => {});
  }, [classId]);
  useEffect(load, [load]);

  return (
    <AgentPanelShell agent="scheduler" classId={classId} onRunComplete={load}>
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <h2 className="font-medium mb-2">Calendar events</h2>
        {events.length === 0 && <p className="text-sm text-gray-600">No events yet.</p>}
        <ul className="text-sm divide-y divide-gray-100">
          {events.map((e) => (
            <li key={e.event_id} className="py-1 flex justify-between">
              <span>{e.date} · {e.title} <span className="text-gray-500">({e.kind})</span></span>
              <span className={e.status === 'published' ? 'text-green-700' : 'text-amber-700'}>{e.status}</span>
            </li>
          ))}
        </ul>
      </div>
    </AgentPanelShell>
  );
};

export default SchedulerPanel;
