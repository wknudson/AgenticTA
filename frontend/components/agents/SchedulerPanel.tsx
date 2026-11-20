import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FileSearch, Sparkles, Wand2 } from 'lucide-react';
import { agentsFetch, RunResult } from '../../services/agentsApi';
import AgentPanelShell from './AgentPanelShell';
import DayEditor from './calendar/DayEditor';
import MonthCalendar from './calendar/MonthCalendar';
import { CalendarEvent, Term, kindLabel, shortDate, startingMonth } from './calendar/calendarUtils';
import type { AgentPanelProps } from './registry';

type Problem = { event?: string; date?: string; problem: string };
type Suggestion = { term: Term | null; sources?: string[]; notes?: string[] };
type Skipped = { title: string; date: string; kind: string; source?: string; problem: string };
type DraftResult = { status: string; output?: string | null; drafted: unknown[]; skipped: Skipped[] };

const emptyTerm: Term = { term_start: '', term_end: '', max_per_day: 2, holidays: [] };
const inputClass = 'border border-gray-300 rounded-lg px-3 py-2 w-full';
const card = 'bg-white rounded-xl border border-gray-200 p-5';

const SchedulerPanel: React.FC<AgentPanelProps> = ({ classId }) => {
  const [term, setTerm] = useState<Term>(emptyTerm);
  const [savedTerm, setSavedTerm] = useState<Term | null>(null);
  const [dirty, setDirty] = useState(false);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [skipped, setSkipped] = useState<Skipped[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [termNotes, setTermNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [publishedOnly, setPublishedOnly] = useState(false);
  const [month, setMonth] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [showAi, setShowAi] = useState(false);
  const [instruction, setInstruction] = useState('Build the calendar from the dates in assignments and filed documents.');
  const saved = savedTerm !== null;

  const load = useCallback(async (signal?: AbortSignal) => {
    const [calendar, conflicts] = await Promise.all([
      agentsFetch<{ events: CalendarEvent[] }>(`/scheduler/events?class_id=${classId}`, { signal }),
      agentsFetch<{ problems: Problem[] }>(`/scheduler/conflicts?class_id=${classId}`, { signal }),
    ]);
    if (!signal?.aborted) { setEvents(calendar.events); setProblems(conflicts.problems); }
    return calendar.events;
  }, [classId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setTerm(emptyTerm); setSavedTerm(null); setDirty(false); setEvents([]); setSkipped([]);
    setError(''); setNotice(''); setTermNotes([]); setSelected(null); setMonth('');
    Promise.all([
      agentsFetch<{ term: Term | null }>(`/scheduler/term?class_id=${classId}`, { signal: controller.signal }),
      load(controller.signal),
    ]).then(([t, evs]) => {
      if (controller.signal.aborted) return;
      setTerm(t.term ?? emptyTerm); setSavedTerm(t.term);
      setMonth(startingMonth(t.term, evs));
    }).catch(e => { if (!controller.signal.aborted) setError(String(e.message)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [classId, load]);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(''); setNotice('');
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const updateTerm = (next: Term) => { setTerm(next); setDirty(true); setNotice(''); };
  const refresh = async () => { try { await load(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } };

  const fillFromSyllabus = () => run(async () => {
    const s = await agentsFetch<Suggestion>(`/scheduler/term/suggest?class_id=${classId}`);
    if (!s.term) { setTermNotes(s.notes ?? []); return; }
    updateTerm(s.term);
    setTermNotes([`Filled from ${s.sources?.join(' and ') ?? 'your documents'}. Check it, then save.`, ...(s.notes ?? [])]);
    if (!month) setMonth(startingMonth(s.term, events));
  });
  const save = (event: React.FormEvent) => {
    event.preventDefault();
    run(async () => {
      const r = await agentsFetch<{ term: Term }>(`/scheduler/term?class_id=${classId}`, { method: 'PUT', body: JSON.stringify(term) });
      setSavedTerm(r.term); setDirty(false); setTermNotes([]);
      setNotice('Term settings saved. Existing events have not been moved.');
      setMonth(m => m || startingMonth(r.term, events));
      await load();
    });
  };
  const draft = () => run(async () => {
    const r = await agentsFetch<DraftResult>(`/scheduler/draft?class_id=${classId}`, { method: 'POST' });
    setSkipped(r.skipped.filter(s => s.problem !== 'already on the calendar'));
    const already = r.skipped.length - r.skipped.filter(s => s.problem !== 'already on the calendar').length;
    setNotice(r.drafted.length
      ? `Drafted ${r.drafted.length} event(s) from your documents and assignments. Open Approvals to publish them.`
      : `Nothing new to schedule${already ? ` (${already} already on the calendar)` : ''}.`);
    await load();
  });
  const buildWithAi = () => run(async () => {
    const result = await agentsFetch<RunResult>('/scheduler/run', { method: 'POST', body: JSON.stringify({ class_id: classId, instruction }) });
    setNotice(result.status === 'waiting_for_approval' ? 'Calendar drafted. Open Approvals to review before publication.' : String(('output' in result ? result.output : null) ?? 'Calendar run completed. Review events and conflicts below.'));
    await load();
  });
  const demoComplete = () => {
    refresh();
    // The explicitly selected demo initializes sample settings only when none exist.
    if (!saved && !dirty) agentsFetch<{ term: Term | null }>(`/scheduler/term?class_id=${classId}`)
      .then(r => { if (r.term) { setTerm(r.term); setSavedTerm(r.term); setMonth(m => m || startingMonth(r.term, events)); } })
      .catch(e => setError(e.message));
  };

  const shown = useMemo(() => events.filter(e => !publishedOnly || e.status === 'published'), [events, publishedOnly]);
  const problemDates = useMemo(() => new Set(problems.map(p => p.date).filter((d): d is string => !!d)), [problems]);
  const pending = events.filter(e => e.status === 'proposed').length;

  return (
    <AgentPanelShell agent="scheduler" classId={classId} onRunComplete={demoComplete}>
      <form onSubmit={save} className={`${card} space-y-4`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold">Term and scheduling rules</h2>
            <p className="text-sm text-gray-600">The term, days off, and how many quizzes or due dates can share a day.</p>
          </div>
          <button type="button" onClick={fillFromSyllabus} disabled={busy || loading}
            className="inline-flex items-center gap-1.5 border border-gray-300 rounded-lg px-3 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-40">
            <FileSearch className="w-4 h-4" /> Fill from syllabus
          </button>
        </div>
        {termNotes.length > 0 && (
          <ul className="text-sm bg-blue-50 text-blue-900 rounded-lg p-3 space-y-1">{termNotes.map(n => <li key={n}>{n}</li>)}</ul>
        )}
        <fieldset disabled={busy || loading} className="space-y-4 disabled:opacity-60">
          <div className="grid sm:grid-cols-3 gap-4">
            <label className="text-sm">Term starts<input className={inputClass} type="date" required value={term.term_start} onChange={e => updateTerm({ ...term, term_start: e.target.value })} /></label>
            <label className="text-sm">Term ends<input className={inputClass} type="date" required min={term.term_start} value={term.term_end} onChange={e => updateTerm({ ...term, term_end: e.target.value })} /></label>
            <label className="text-sm">Max quizzes + due dates / day<input className={inputClass} type="number" required min={1} max={20} value={term.max_per_day} onChange={e => updateTerm({ ...term, max_per_day: Number(e.target.value) })} /></label>
          </div>
          <p className="text-sm text-gray-600">Weekends are always excluded.</p>
          {term.holidays.map((holiday, index) => (
            <div key={index} className="flex flex-wrap gap-2 items-end">
              <label className="text-sm">No school on<input className={inputClass} type="date" required min={term.term_start} max={term.term_end} value={holiday.date} onChange={e => updateTerm({ ...term, holidays: term.holidays.map((h, i) => i === index ? { ...h, date: e.target.value } : h) })} /></label>
              <label className="text-sm flex-1 min-w-[10rem]">Reason<input className={inputClass} required maxLength={120} value={holiday.label} onChange={e => updateTerm({ ...term, holidays: term.holidays.map((h, i) => i === index ? { ...h, label: e.target.value } : h) })} /></label>
              <button type="button" className="px-3 py-2 text-sm text-red-700" onClick={() => updateTerm({ ...term, holidays: term.holidays.filter((_, i) => i !== index) })}>Remove</button>
            </div>
          ))}
          <div className="flex gap-3">
            <button type="button" className="border rounded-lg px-3 py-2 text-sm" onClick={() => updateTerm({ ...term, holidays: [...term.holidays, { date: '', label: '' }] })}>Add a day off</button>
            <button type="submit" disabled={!dirty} className="bg-black text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40">Save settings</button>
          </div>
        </fieldset>
      </form>

      <div className={`${card} space-y-3`}>
        <h2 className="font-semibold">Build the calendar</h2>
        <div className="flex flex-wrap gap-3 items-center">
          <button onClick={draft} disabled={busy || loading || !saved || dirty}
            className="inline-flex items-center gap-1.5 bg-black text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40">
            <Wand2 className="w-4 h-4" /> {busy ? 'Working…' : 'Draft from documents'}
          </button>
          <button type="button" onClick={() => setShowAi(v => !v)} className="inline-flex items-center gap-1.5 text-sm text-gray-700 underline">
            <Sparkles className="w-4 h-4" /> {showAi ? 'Hide' : 'Or build with AI'}
          </button>
        </div>
        <p className="text-sm text-gray-600">
          Reads the dates in your filed documents and assignments, merges duplicates, and checks every rule. No AI needed.
          Drafted events wait in Approvals before students see them.
        </p>
        {showAi && (
          <div className="rounded-lg border border-gray-200 p-3 space-y-2">
            <label className="block text-sm font-medium">Instruction for the scheduler agent
              <textarea className={`${inputClass} mt-1 font-normal`} value={instruction} onChange={e => setInstruction(e.target.value)} />
            </label>
            <button className="border border-gray-900 rounded-lg px-4 py-2 text-sm disabled:opacity-40" disabled={busy || loading || !saved || dirty || !instruction.trim()} onClick={buildWithAi}>Build with AI</button>
            <p className="text-xs text-gray-500">Uses the scheduler's model (needs its API key in the scheduler .env).</p>
          </div>
        )}
        {!saved && !loading && <p className="text-sm text-amber-700">Save the term settings first.</p>}
        {dirty && <p className="text-sm text-amber-700">Save your settings before building.</p>}
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        {notice && <p role="status" className="text-sm text-green-800">{notice}</p>}
        {skipped.length > 0 && (
          <div className="bg-amber-50 text-amber-950 rounded-lg p-3">
            <h3 className="font-medium text-sm">Needs your call ({skipped.length})</h3>
            <p className="text-xs text-amber-900 mb-2">These dates were found but break a rule, so they weren't drafted. Add them on the calendar on a different day, or change the rules.</p>
            <ul className="text-sm space-y-1">
              {skipped.map((s, i) => (
                <li key={i}>
                  <button type="button" className="underline decoration-dotted" onClick={() => { setSelected(s.date); setMonth(`${s.date.slice(0, 7)}-01`); }}>
                    {shortDate(s.date)}
                  </button>{' '}· {s.title} <span className="text-amber-800">({kindLabel(s.kind)}: {s.problem})</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className={card}>
        <div className="flex flex-wrap justify-between gap-3 mb-3">
          <div>
            <h2 className="font-semibold">Class calendar</h2>
            <p className="text-sm text-gray-600">
              Click a day to add, move, or remove events.
              {pending > 0 && <> {pending} event(s) are waiting in Approvals.</>}
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={publishedOnly} onChange={e => setPublishedOnly(e.target.checked)} /> Published only</label>
            <button onClick={refresh} className="underline">Refresh</button>
          </div>
        </div>
        {problems.length > 0 && (
          <div className="bg-red-50 text-red-900 p-3 rounded-lg mb-3 text-sm">
            <h3 className="font-medium">Conflicts in proposed events</h3>
            <ul className="list-disc pl-5">{problems.map((p, i) => <li key={i}>{p.date} {p.event}: {p.problem}</li>)}</ul>
          </div>
        )}
        {loading ? <p className="text-sm text-gray-600">Loading calendar…</p> : (
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] gap-5">
            <MonthCalendar month={month || startingMonth(savedTerm, events)} onMonthChange={setMonth}
              events={shown} term={savedTerm} problemDates={problemDates} selected={selected} onSelect={setSelected} />
            <aside className="min-w-0 lg:border-l lg:border-gray-200 lg:pl-5">
              {selected ? (
                <DayEditor classId={classId} date={selected} term={savedTerm}
                  events={events.filter(e => e.date === selected)}
                  problems={problems.filter(p => p.date === selected).map(p => `${p.event ? `${p.event}: ` : ''}${p.problem}`)}
                  onChanged={refresh} />
              ) : (
                <p className="text-sm text-gray-500">Select a day to see or change what's on it.</p>
              )}
            </aside>
          </div>
        )}
      </div>
    </AgentPanelShell>
  );
};
export default SchedulerPanel;
