import React, { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { agentsFetch } from '../../../services/agentsApi';
import { CalendarEvent, KINDS, Term, kindLabel, kindStyle, longDate } from './calendarUtils';

/** Teacher side panel for one day: edit, move, or remove its events, or add a new one.
 * Every change is rechecked by the scheduler's rules on the server. */
interface Props {
  classId: number;
  date: string;
  events: CalendarEvent[];
  term: Term | null;
  problems: string[];
  onChanged: () => Promise<void> | void;
  /** false when the parent already shows the date, the day off and the conflicts (default true). */
  showHeader?: boolean;
  /** Shown when the day has no events (default "Nothing scheduled."). */
  emptyText?: string;
}

const input = 'border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm w-full';

const EventRow: React.FC<{ classId: number; event: CalendarEvent; onChanged: Props['onChanged'] }> = ({ classId, event, onChanged }) => {
  const [draft, setDraft] = useState({ title: event.title, date: event.date, kind: event.kind });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { setDraft({ title: event.title, date: event.date, kind: event.kind }); setError(''); }, [event]);
  const changed = draft.title !== event.title || draft.date !== event.date || draft.kind !== event.kind;

  const call = async (init: RequestInit) => {
    setBusy(true); setError('');
    try {
      await agentsFetch(`/scheduler/events/${event.event_id}?class_id=${classId}`, init);
      await onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  return (
    <li className="rounded-xl border border-gray-200 p-3 space-y-2">
      <div className="flex items-center gap-2 text-xs">
        <span className={`w-2 h-2 rounded-full ${kindStyle(event.kind).dot}`} />
        <span className="text-gray-600">{kindLabel(event.kind)}</span>
        <span className={`ml-auto font-medium ${event.status === 'published' ? 'text-green-700' : 'text-amber-700'}`}>
          {event.status === 'published' ? 'Published' : 'Waiting for approval'}
        </span>
      </div>
      <input className={input} aria-label="Event title" value={draft.title} maxLength={200}
        onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
      <div className="grid grid-cols-2 gap-2">
        <input className={input} type="date" aria-label="Event date" value={draft.date}
          onChange={(e) => setDraft({ ...draft, date: e.target.value })} />
        <select className={input} aria-label="Event type" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
          {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
      </div>
      {event.source && <p className="text-xs text-gray-500 truncate" title={event.source}>From: {event.source}</p>}
      {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={!changed || busy || !draft.title.trim() || !draft.date}
          onClick={() => call({ method: 'PATCH', body: JSON.stringify(draft) })}
          className="px-3 py-1.5 text-sm rounded-lg bg-black text-white disabled:opacity-30">Save</button>
        <button type="button" disabled={busy} onClick={() => call({ method: 'DELETE' })}
          className="px-2.5 py-1.5 text-sm rounded-lg text-red-700 hover:bg-red-50 inline-flex items-center gap-1">
          <Trash2 className="w-3.5 h-3.5" /> Remove
        </button>
      </div>
    </li>
  );
};

const DayEditor: React.FC<Props> = ({ classId, date, events, term, problems, onChanged, showHeader = true, emptyText = 'Nothing scheduled.' }) => {
  const [title, setTitle] = useState('');
  const [kind, setKind] = useState('assessment');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { setTitle(''); setError(''); }, [date]);
  const holiday = term?.holidays.find((h) => h.date === date);

  const add = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError('');
    try {
      await agentsFetch(`/scheduler/events?class_id=${classId}`, { method: 'POST', body: JSON.stringify({ title, date, kind }) });
      setTitle('');
      await onChanged();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-3">
      {showHeader && (
        <div>
          <h3 className="font-semibold text-gray-900">{longDate(date)}</h3>
          {holiday && <p className="text-sm text-amber-800">No school: {holiday.label}</p>}
          {problems.map((p) => <p key={p} className="text-sm text-red-700">Conflict: {p}</p>)}
        </div>
      )}
      {events.length > 0
        ? <ul className="space-y-2">{events.map((e) => <EventRow key={e.event_id} classId={classId} event={e} onChanged={onChanged} />)}</ul>
        : <p className="text-sm text-gray-500">{emptyText}</p>}
      <form onSubmit={add} className="rounded-xl bg-gray-50 border border-gray-200 p-3 space-y-2">
        <p className="text-sm font-medium text-gray-900">Add to this day</p>
        <input className={input} aria-label="New event title" placeholder="e.g. Unit 3 quiz" required maxLength={200}
          value={title} onChange={(e) => setTitle(e.target.value)} />
        <div className="flex gap-2">
          <select className={input} aria-label="New event type" value={kind} onChange={(e) => setKind(e.target.value)}>
            {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
          <button type="submit" disabled={busy || !title.trim()}
            className="shrink-0 px-3 py-1.5 text-sm rounded-lg bg-black text-white disabled:opacity-30 inline-flex items-center gap-1">
            <Plus className="w-3.5 h-3.5" /> Add
          </button>
        </div>
        <p className="text-xs text-gray-500">Events you add are published right away; students will see them.</p>
        {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
      </form>
    </div>
  );
};

export default DayEditor;
