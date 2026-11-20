import React, { useCallback, useEffect, useState } from 'react';
import { agentsFetch, RunResult } from '../../services/agentsApi';
import AgentPanelShell from './AgentPanelShell';
import type { AgentPanelProps } from './registry';

type Term = { term_start: string; term_end: string; max_per_day: number; holidays: { date: string; label: string }[] };
type CalendarEvent = { event_id: number; title: string; kind: string; date: string; status: string };
type Problem = { event?: string; date?: string; problem: string };
const emptyTerm: Term = { term_start: '', term_end: '', max_per_day: 2, holidays: [] };
const inputClass = 'border border-gray-300 rounded-lg px-3 py-2 w-full';

const SchedulerPanel: React.FC<AgentPanelProps> = ({ classId }) => {
  const [term, setTerm] = useState<Term>(emptyTerm);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [publishedOnly, setPublishedOnly] = useState(false);
  const [instruction, setInstruction] = useState('Build the calendar from the dates in assignments and filed documents.');

  const load = useCallback(async (signal?: AbortSignal) => {
    const [calendar, conflicts] = await Promise.all([
      agentsFetch<{ events: CalendarEvent[] }>(`/scheduler/events?class_id=${classId}`, { signal }),
      agentsFetch<{ problems: Problem[] }>(`/scheduler/conflicts?class_id=${classId}`, { signal }),
    ]);
    if (!signal?.aborted) { setEvents(calendar.events); setProblems(conflicts.problems); }
  }, [classId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setTerm(emptyTerm); setSaved(false); setDirty(false); setEvents([]); setError(''); setNotice('');
    Promise.all([
      agentsFetch<{ term: Term | null }>(`/scheduler/term?class_id=${classId}`, { signal: controller.signal })
        .then(r => { if (!controller.signal.aborted) { setTerm(r.term ?? emptyTerm); setSaved(!!r.term); } }),
      load(controller.signal),
    ]).catch(e => { if (!controller.signal.aborted) setError(String(e.message)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [classId, load]);

  const updateTerm = (next: Term) => { setTerm(next); setDirty(true); setNotice(''); };
  const refresh = () => { load().catch(e => setError(e.message)); };
  const save = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      await agentsFetch(`/scheduler/term?class_id=${classId}`, { method: 'PUT', body: JSON.stringify(term) });
      setSaved(true); setDirty(false); setNotice('Term settings saved. Existing events have not been moved.'); await load();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const build = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await agentsFetch<RunResult>('/scheduler/run', { method: 'POST', body: JSON.stringify({ class_id: classId, instruction }) });
      setNotice(result.status === 'waiting_for_approval' ? 'Calendar drafted. Open Approvals to review before publication.' : String(('output' in result ? result.output : null) ?? 'Calendar run completed. Review events and conflicts below.'));
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const demoComplete = () => {
    refresh();
    // The explicitly selected demo initializes sample settings only when none exist.
    if (!saved && !dirty) agentsFetch<{ term: Term | null }>(`/scheduler/term?class_id=${classId}`)
      .then(r => { if (r.term) { setTerm(r.term); setSaved(true); } }).catch(e => setError(e.message));
  };

  return (
    <AgentPanelShell agent="scheduler" classId={classId} onRunComplete={demoComplete}>
      <form onSubmit={save} className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <h2 className="font-semibold">Term and scheduling rules</h2>
        <p className="text-sm text-gray-600">Choose the term, holidays, and daily assessment limit before building the calendar. The offline demo uses sample settings if none are saved.</p>
        <fieldset disabled={busy || loading} className="space-y-4 disabled:opacity-60">
          <div className="grid sm:grid-cols-3 gap-4">
            <label>Term starts<input className={inputClass} type="date" required value={term.term_start} onChange={e => updateTerm({ ...term, term_start: e.target.value })} /></label>
            <label>Term ends<input className={inputClass} type="date" required min={term.term_start} value={term.term_end} onChange={e => updateTerm({ ...term, term_end: e.target.value })} /></label>
            <label>Max assessments / day<input className={inputClass} type="number" required min={1} max={20} value={term.max_per_day} onChange={e => updateTerm({ ...term, max_per_day: Number(e.target.value) })} /></label>
          </div>
          <p className="text-sm text-gray-600">The limit counts assessments and assignment due dates together. Weekends are always excluded.</p>
          {term.holidays.map((holiday, index) => (
            <div key={index} className="flex flex-wrap gap-2 items-end">
              <label>Holiday date<input className={inputClass} type="date" required min={term.term_start} max={term.term_end} value={holiday.date} onChange={e => updateTerm({ ...term, holidays: term.holidays.map((h, i) => i === index ? { ...h, date: e.target.value } : h) })} /></label>
              <label>Label<input className={inputClass} required maxLength={120} value={holiday.label} onChange={e => updateTerm({ ...term, holidays: term.holidays.map((h, i) => i === index ? { ...h, label: e.target.value } : h) })} /></label>
              <button type="button" className="px-3 py-2 text-red-700" onClick={() => updateTerm({ ...term, holidays: term.holidays.filter((_, i) => i !== index) })}>Remove holiday</button>
            </div>
          ))}
          <div className="flex gap-3">
            <button type="button" className="border rounded-lg px-3 py-2" onClick={() => updateTerm({ ...term, holidays: [...term.holidays, { date: '', label: '' }] })}>Add holiday</button>
            <button type="submit" className="bg-black text-white rounded-lg px-4 py-2">Save settings</button>
          </div>
        </fieldset>
      </form>
      <div className="bg-white border rounded-xl p-5 space-y-3">
        <label className="block font-medium">Calendar instruction<textarea className={`${inputClass} mt-2 font-normal`} value={instruction} onChange={e => setInstruction(e.target.value)} /></label>
        <button className="bg-black text-white rounded-lg px-4 py-2 disabled:opacity-40" disabled={busy || loading || !saved || dirty || !instruction.trim()} onClick={build}>{busy ? 'Working…' : 'Build calendar'}</button>
        {dirty && <p className="text-sm text-amber-700">Save your settings before building.</p>}
        {error && <p role="alert" className="text-red-700">{error}</p>}
        {notice && <p role="status" className="text-sm text-green-800">{notice}</p>}
      </div>
      <div className="bg-white rounded-xl border p-5">
        <div className="flex justify-between gap-4 mb-3"><h2 className="font-semibold">Calendar events</h2><button onClick={refresh} className="underline">Refresh after approval</button></div>
        <label className="text-sm"><input type="checkbox" checked={publishedOnly} onChange={e => setPublishedOnly(e.target.checked)} /> Show published events only</label>
        {problems.length > 0 && <div className="bg-amber-50 text-amber-900 p-3 rounded-lg my-3"><h3 className="font-medium">Conflicts in proposed events</h3><ul className="list-disc pl-5">{problems.map((p, i) => <li key={i}>{p.date} {p.event}: {p.problem}</li>)}</ul></div>}
        <ul className="text-sm divide-y mt-3">{events.filter(e => !publishedOnly || e.status === 'published').map(e => <li key={e.event_id} className="py-3 flex justify-between gap-3"><span>{e.date} · {e.title}</span><span className={e.status === 'published' ? 'text-green-700' : 'text-amber-700'}>{e.status}</span></li>)}</ul>
        {!events.some(e => !publishedOnly || e.status === 'published') && <p className="text-sm text-gray-600 mt-3">No {publishedOnly ? 'published ' : ''}events yet.</p>}
      </div>
    </AgentPanelShell>
  );
};
export default SchedulerPanel;
