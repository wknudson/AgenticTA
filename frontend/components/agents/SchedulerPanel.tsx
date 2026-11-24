import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, FileSearch, Sparkles, Wand2, X } from 'lucide-react';
import { agentsFetch, RunResult } from '../../services/agentsApi';
import { updateCheckinSettings } from '../../services/checkinSettingsApi';
import { getSchedulerFeed, moveSchedulerEvent, type FeedCheckin, type SchedulerFeed } from '../../services/schedulerFeedApi';
import { formatDue } from '../checkin/format';
import AgentPanelShell from './AgentPanelShell';
import ClassCalendar, { type CalendarDrag } from './calendar/ClassCalendar';
import DayPanel from './calendar/DayPanel';
import SuggestCheckins from './calendar/SuggestCheckins';
import { Term, kindLabel, longDate, monthGrid, monthOf, shortDate, startingMonth } from './calendar/calendarUtils';
import { buildDayIndex, checkinColors, dueBeforeLesson, emptyDay } from './calendar/classCalendarData';
import type { AgentPanelProps } from './registry';

type Problem = { event?: string; date?: string; problem: string };
type Suggestion = { term: Term | null; sources?: string[]; notes?: string[] };
type Skipped = { title: string; date: string; kind: string; source?: string; problem: string };
type DraftResult = { status: string; output?: string | null; drafted: unknown[]; skipped: Skipped[] };
/** Where a message shows: above the calendar, or in the section whose button caused it. */
type Where = 'top' | 'term' | 'build';
type Message = { at: Where; text: string };
type MoveMessage = { tone: 'ok' | 'warn' | 'error'; lines: string[] };
type SectionKey = 'term' | 'build' | 'suggest';

const emptyTerm: Term = { term_start: '', term_end: '', max_per_day: 2, holidays: [] };
const inputClass = 'border border-gray-300 rounded-lg px-3 py-2 w-full';
const card = 'bg-white rounded-xl border border-gray-200';
const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * The feed's date range: the whole term (as whole month grids) plus the month on screen, so moving
 * between months of the term doesn't refetch.
 */
function feedRange(month: string, term: Term | null): { start: string; end: string } {
  const grid = monthGrid(month);
  let start = grid[0];
  let end = grid[grid.length - 1];
  if (term?.term_start && term.term_end && term.term_start <= term.term_end) {
    const first = monthGrid(monthOf(term.term_start))[0];
    const lastGrid = monthGrid(monthOf(term.term_end));
    const last = lastGrid[lastGrid.length - 1];
    if (first < start) start = first;
    if (last > end) end = last;
  }
  return { start, end };
}

const Section: React.FC<{
  id: string; title: string; subtitle: string; open: boolean; onToggle: () => void; children: React.ReactNode;
}> = ({ id, title, subtitle, open, onToggle, children }) => (
  <section className={card}>
    <h2>
      <button type="button" aria-expanded={open} aria-controls={id} onClick={onToggle}
        className="w-full flex items-center justify-between gap-3 p-4 sm:p-5 text-left rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ba3638]">
        <span className="min-w-0">
          <span className="block font-semibold text-gray-900">{title}</span>
          <span className="block text-sm font-normal text-gray-600">{subtitle}</span>
        </span>
        <ChevronDown className={`w-5 h-5 shrink-0 text-gray-500 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
    </h2>
    {/* Kept mounted while closed, so what's typed or found there survives a collapse. */}
    <div id={id} hidden={!open} className="px-4 sm:px-5 pb-5 space-y-4">{children}</div>
  </section>
);

const SchedulerPanel: React.FC<AgentPanelProps> = ({ classId, onOpenCheckin, onOpenBriefing, onOpenApprovals, onStartCheckin }) => {
  const [term, setTerm] = useState<Term>(emptyTerm);
  const [savedTerm, setSavedTerm] = useState<Term | null>(null);
  const [dirty, setDirty] = useState(false);
  const [feed, setFeed] = useState<SchedulerFeed | null>(null);
  const [feedError, setFeedError] = useState('');
  const [problems, setProblems] = useState<Problem[]>([]);
  const [skipped, setSkipped] = useState<Skipped[]>([]);
  const [error, setError] = useState<Message | null>(null);
  const [notice, setNotice] = useState<Message | null>(null);
  const [termNotes, setTermNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [publishedOnly, setPublishedOnly] = useState(false);
  const [month, setMonth] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [showAi, setShowAi] = useState(false);
  const [instruction, setInstruction] = useState('Build the calendar from the dates in assignments and filed documents.');
  const [moving, setMoving] = useState(false);
  const [moveMsg, setMoveMsg] = useState<MoveMessage | null>(null);
  const [open, setOpen] = useState<Record<SectionKey, boolean>>({ term: false, build: false, suggest: false });
  const calendarRef = useRef<HTMLDivElement>(null);
  const saved = savedTerm !== null;

  const range = useMemo(() => (month ? feedRange(month, savedTerm) : null), [month, savedTerm]);
  const rangeStart = range?.start ?? '';
  const rangeEnd = range?.end ?? '';

  const loadFeed = useCallback(async (signal?: AbortSignal) => {
    if (!rangeStart || !rangeEnd) return;
    const f = await getSchedulerFeed(classId, rangeStart, rangeEnd, signal);
    if (!signal?.aborted) { setFeed(f); setFeedError(''); }
  }, [classId, rangeStart, rangeEnd]);

  const loadConflicts = useCallback(async (signal?: AbortSignal) => {
    const c = await agentsFetch<{ problems: Problem[] }>(`/scheduler/conflicts?class_id=${classId}`, { signal });
    if (!signal?.aborted) setProblems(c.problems);
  }, [classId]);

  // A new class: its term (which sets the month, and so the feed's range) and conflicts.
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setTerm(emptyTerm); setSavedTerm(null); setDirty(false); setFeed(null); setFeedError(''); setSkipped([]);
    setError(null); setNotice(null); setTermNotes([]); setSelected(null); setMonth(''); setMoveMsg(null); setProblems([]);
    Promise.all([
      agentsFetch<{ term: Term | null }>(`/scheduler/term?class_id=${classId}`, { signal: controller.signal }),
      loadConflicts(controller.signal).catch(() => { /* conflicts are a nice-to-have; Refresh retries */ }),
    ]).then(([t]) => {
      if (controller.signal.aborted) return;
      setTerm(t.term ?? emptyTerm); setSavedTerm(t.term);
      setMonth(startingMonth(t.term, []));
      setOpen((o) => ({ ...o, term: !t.term }));
    }).catch((e) => {
      if (controller.signal.aborted) return;
      setError({ at: 'top', text: errorText(e) });
      setMonth((m) => m || startingMonth(null, []));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [classId, loadConflicts]);

  // The feed follows the range (a new term, or a month outside it).
  useEffect(() => {
    const controller = new AbortController();
    loadFeed(controller.signal).catch((e) => { if (!controller.signal.aborted) setFeedError(errorText(e)); });
    return () => controller.abort();
  }, [loadFeed]);

  const refresh = useCallback(async () => {
    try { await Promise.all([loadFeed(), loadConflicts()]); } catch (e) { setFeedError(errorText(e)); }
  }, [loadFeed, loadConflicts]);

  const run = async (at: Where, fn: () => Promise<void>) => {
    setBusy(true); setError(null); setNotice(null);
    try { await fn(); } catch (e) { setError({ at, text: errorText(e) }); } finally { setBusy(false); }
  };
  const updateTerm = (next: Term) => { setTerm(next); setDirty(true); setNotice(null); };
  const toggle = (key: SectionKey) => setOpen((o) => ({ ...o, [key]: !o[key] }));
  const showDay = (day: string) => {
    setSelected(day); setMonth(monthOf(day));
    calendarRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const fillFromSyllabus = () => run('term', async () => {
    const s = await agentsFetch<Suggestion>(`/scheduler/term/suggest?class_id=${classId}`);
    if (!s.term) { setTermNotes(s.notes ?? []); return; }
    updateTerm(s.term);
    setTermNotes([`Filled from ${s.sources?.join(' and ') ?? 'your documents'}. Check it, then save.`, ...(s.notes ?? [])]);
  });
  const save = (event: React.FormEvent) => {
    event.preventDefault();
    run('term', async () => {
      const r = await agentsFetch<{ term: Term }>(`/scheduler/term?class_id=${classId}`, { method: 'PUT', body: JSON.stringify(term) });
      setSavedTerm(r.term); setDirty(false); setTermNotes([]);
      setNotice({ at: 'term', text: 'Term settings saved. Existing events have not been moved.' });
      setMonth((m) => m || startingMonth(r.term, []));
      await loadConflicts(); // the feed refetches itself for the new term's range
    });
  };
  const draft = () => run('build', async () => {
    const r = await agentsFetch<DraftResult>(`/scheduler/draft?class_id=${classId}`, { method: 'POST' });
    const needsCall = r.skipped.filter((s) => s.problem !== 'already on the calendar');
    setSkipped(needsCall);
    const already = r.skipped.length - needsCall.length;
    setNotice({
      at: 'build',
      text: r.drafted.length
        ? `Drafted ${r.drafted.length} event(s) from your documents and assignments. They're dashed on the calendar; open Approvals to publish them.`
        : `Nothing new to schedule${already ? ` (${already} already on the calendar)` : ''}.`,
    });
    await refresh();
  });
  const buildWithAi = () => run('build', async () => {
    const result = await agentsFetch<RunResult>('/scheduler/run', { method: 'POST', body: JSON.stringify({ class_id: classId, instruction }) });
    setNotice({
      at: 'build',
      text: result.status === 'waiting_for_approval'
        ? 'Calendar drafted. Open Approvals to review before publication.'
        : String(('output' in result ? result.output : null) ?? 'Calendar run completed. Review events and conflicts on the calendar.'),
    });
    await refresh();
  });
  const demoComplete = () => {
    refresh();
    // The explicitly selected demo initializes sample settings only when none exist.
    if (!saved && !dirty) agentsFetch<{ term: Term | null }>(`/scheduler/term?class_id=${classId}`)
      .then((r) => { if (r.term) { setTerm(r.term); setSavedTerm(r.term); setMonth((m) => m || startingMonth(r.term, [])); } })
      .catch((e) => setError({ at: 'top', text: errorText(e) }));
  };

  // ---- Moves (drag and drop, or the day panel's date fields)
  const moveEvent = async (item: Extract<CalendarDrag, { type: 'event' }>, day: string) => {
    const ev = item.event;
    setFeed((f) => f && { ...f, events: f.events.map((e) => (e.event_id === ev.event_id ? { ...e, date: day } : e)) });
    try {
      await moveSchedulerEvent(classId, ev.event_id, day);
      setMoveMsg({ tone: 'ok', lines: [`Moved "${ev.title}" to ${longDate(day)}.${ev.status === 'published' ? ' Students see the new date.' : ''}`] });
      setSelected(day);
    } catch (e) {
      setMoveMsg({ tone: 'error', lines: [`Couldn't move "${ev.title}": ${errorText(e)}`] });
    }
  };

  const moveCheckin = async (c: FeedCheckin, day: string) => {
    // The due moves to the evening before the new lesson, keeping its local time.
    const due = dueBeforeLesson(day, c.due_date);
    setFeed((f) => f && {
      ...f,
      checkins: f.checkins.map((x) => (x.assignment_id === c.assignment_id ? { ...x, lesson_date: day, ...due } : x)),
    });
    try {
      const res = await updateCheckinSettings(c.assignment_id, { lesson_date: day, ...due });
      const notes = res.notes.filter((n) => n !== 'Nothing changed.');
      // Same reading as the check-in settings form: a calendar note that isn't "moved/added" is a problem.
      const calendarTrouble = !!res.calendar_note && !/^Calendar: (moved|added)/.test(res.calendar_note);
      const lines = [`Moved the "${c.title}" lesson to ${longDate(day)}; due ${formatDue(due.due_date)}.`, ...notes];
      if (new Date(due.due_date).getTime() < Date.now()) lines.push("That due time has passed: students won't be able to change their answers.");
      setMoveMsg({ tone: calendarTrouble ? 'warn' : 'ok', lines });
      setSelected(day);
    } catch (e) {
      setMoveMsg({ tone: 'error', lines: [`Couldn't move "${c.title}": ${errorText(e)}`] });
    }
  };

  const withMove = async (fn: () => Promise<void>) => {
    if (moving) return;
    setMoving(true); setMoveMsg(null);
    try { await fn(); } finally {
      await refresh(); // the server's version wins (and undoes the optimistic move after an error)
      setMoving(false);
    }
  };
  const onMove = (item: CalendarDrag, day: string) =>
    withMove(() => (item.type === 'event' ? moveEvent(item, day) : moveCheckin(item.checkin, day)));
  const onMoveCheckin = (c: FeedCheckin, day: string) => withMove(() => moveCheckin(c, day));

  // ---- What the calendar shows
  const events = useMemo(() => (feed?.events ?? []).filter((e) => !publishedOnly || e.status === 'published'), [feed, publishedOnly]);
  const checkins = useMemo(() => feed?.checkins ?? [], [feed]);
  const drafts = useMemo(() => (publishedOnly ? [] : feed?.drafts ?? []), [feed, publishedOnly]);
  const assignments = useMemo(() => feed?.assignments ?? [], [feed]);
  const index = useMemo(() => buildDayIndex({ events, checkins, drafts, assignments }), [events, checkins, drafts, assignments]);
  const colors = useMemo(() => checkinColors(checkins), [checkins]);
  const problemDates = useMemo(() => new Set(problems.map((p) => p.date).filter((d): d is string => !!d)), [problems]);
  const pendingEvents = (feed?.events ?? []).filter((e) => e.status === 'proposed').length;
  const pendingDrafts = feed?.drafts.length ?? 0;
  const calendarTerm = savedTerm ?? feed?.term ?? null;

  const messageAt = (at: Where) => (
    <>
      {error?.at === at && <p role="alert" className="text-sm text-red-700">{error.text}</p>}
      {notice?.at === at && <p role="status" className="text-sm text-green-800">{notice.text}</p>}
    </>
  );

  return (
    <AgentPanelShell agent="scheduler" classId={classId} onRunComplete={demoComplete}>
      <div ref={calendarRef} className={`${card} p-3 sm:p-5 space-y-3 scroll-mt-4`}>
        <div className="flex flex-wrap justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-gray-900">Class calendar</h2>
            <p className="text-sm text-gray-600">
              Check-ins, their practice windows, due dates and events, month by month. Click a day to see or change it.
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <label className="flex items-center gap-1.5"><input type="checkbox" checked={publishedOnly} onChange={(e) => setPublishedOnly(e.target.checked)} /> Published only</label>
            <button type="button" onClick={refresh} className="underline">Refresh</button>
          </div>
        </div>

        {(pendingEvents > 0 || pendingDrafts > 0) && (
          <p className="text-sm text-amber-900 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
            Waiting for approval (dashed):{' '}
            {[pendingEvents > 0 && `${pendingEvents} event${pendingEvents === 1 ? '' : 's'}`,
              pendingDrafts > 0 && `${pendingDrafts} check-in draft${pendingDrafts === 1 ? '' : 's'}`].filter(Boolean).join(' and ')}.
            {onOpenApprovals && <> <button type="button" className="underline font-medium" onClick={onOpenApprovals}>Open Approvals</button></>}
          </p>
        )}
        {!saved && !loading && (
          <p className="text-sm text-gray-700 rounded-lg bg-gray-50 border border-gray-200 px-3 py-2">
            No term saved yet: weekends are shaded, but holidays and the term aren't.{' '}
            <button type="button" className="underline" onClick={() => setOpen((o) => ({ ...o, term: true }))}>Set the term below</button>.
          </p>
        )}
        {messageAt('top')}
        {feedError && <p role="alert" className="text-sm text-red-700">Couldn't load the calendar: {feedError}</p>}
        {!feed && !feedError && !loading && <p className="text-xs text-gray-500">Loading check-ins, events and due dates…</p>}
        {moveMsg && (
          <div role={moveMsg.tone === 'error' ? 'alert' : 'status'}
            className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm ${
              moveMsg.tone === 'error' ? 'bg-red-50 border-red-200 text-red-900'
                : moveMsg.tone === 'warn' ? 'bg-amber-50 border-amber-200 text-amber-900' : 'bg-emerald-50 border-emerald-200 text-emerald-900'}`}>
            <ul className="flex-1 min-w-0 space-y-0.5 break-words">{moveMsg.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
            <button type="button" aria-label="Dismiss" onClick={() => setMoveMsg(null)} className="p-0.5 rounded hover:bg-black/5 shrink-0">
              <X className="w-4 h-4" aria-hidden="true" />
            </button>
          </div>
        )}
        {problems.length > 0 && (
          <div className="bg-red-50 text-red-900 p-3 rounded-lg text-sm">
            <h3 className="font-medium">Conflicts in proposed events</h3>
            <ul className="list-disc pl-5">
              {problems.map((p, i) => (
                <li key={i}>
                  {p.date ? <button type="button" className="underline decoration-dotted" onClick={() => showDay(p.date!)}>{shortDate(p.date)}</button> : null}
                  {' '}{p.event}: {p.problem}
                </li>
              ))}
            </ul>
          </div>
        )}

        {loading || !month ? <p className="text-sm text-gray-600">Loading calendar…</p> : (
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_288px] gap-5">
            <ClassCalendar
              month={month}
              onMonthChange={setMonth}
              term={calendarTerm}
              events={events}
              checkins={checkins}
              drafts={drafts}
              assignments={assignments}
              problemDates={problemDates}
              selected={selected}
              onSelect={setSelected}
              onMove={moving ? undefined : onMove}
              onRefuse={(message) => setMoveMsg({ tone: 'warn', lines: [message] })}
            />
            <aside className="min-w-0 border-t border-gray-200 pt-4 lg:border-t-0 lg:pt-0 lg:border-l lg:pl-5" aria-label="Selected day">
              {selected ? (
                <DayPanel
                  classId={classId}
                  day={selected}
                  term={calendarTerm}
                  items={index[selected] ?? emptyDay()}
                  colors={colors}
                  problems={problems.filter((p) => p.date === selected).map((p) => `${p.event ? `${p.event}: ` : ''}${p.problem}`)}
                  onChanged={refresh}
                  onMoveCheckin={onMoveCheckin}
                  moving={moving}
                  onOpenCheckin={onOpenCheckin}
                  onOpenBriefing={onOpenBriefing}
                  onOpenApprovals={onOpenApprovals}
                  onStartCheckin={onStartCheckin}
                />
              ) : (
                <p className="text-sm text-gray-500">Select a day to see its check-ins, events and due dates, add an event, or start a check-in for that lesson.</p>
              )}
            </aside>
          </div>
        )}
      </div>

      <Section id="scheduler-term" title="Term and scheduling rules" open={open.term} onToggle={() => toggle('term')}
        subtitle={savedTerm ? `${shortDate(savedTerm.term_start)} to ${shortDate(savedTerm.term_end)} · ${savedTerm.holidays.length} day${savedTerm.holidays.length === 1 ? '' : 's'} off · up to ${savedTerm.max_per_day} per day`
          : 'The term, days off, and how many quizzes or due dates can share a day.'}>
        <form onSubmit={save} className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <p className="text-sm text-gray-600">The term, days off, and how many quizzes or due dates can share a day.</p>
            <button type="button" onClick={fillFromSyllabus} disabled={busy || loading}
              className="inline-flex items-center gap-1.5 border border-gray-300 rounded-lg px-3 py-2 text-sm font-medium hover:bg-gray-50 disabled:opacity-40">
              <FileSearch className="w-4 h-4" /> Fill from syllabus
            </button>
          </div>
          {termNotes.length > 0 && (
            <ul className="text-sm bg-blue-50 text-blue-900 rounded-lg p-3 space-y-1">{termNotes.map((n) => <li key={n}>{n}</li>)}</ul>
          )}
          <fieldset disabled={busy || loading} className="space-y-4 disabled:opacity-60">
            <div className="grid sm:grid-cols-3 gap-4">
              <label className="text-sm">Term starts<input className={inputClass} type="date" required value={term.term_start} onChange={(e) => updateTerm({ ...term, term_start: e.target.value })} /></label>
              <label className="text-sm">Term ends<input className={inputClass} type="date" required min={term.term_start} value={term.term_end} onChange={(e) => updateTerm({ ...term, term_end: e.target.value })} /></label>
              <label className="text-sm">Max quizzes + due dates / day<input className={inputClass} type="number" required min={1} max={20} value={term.max_per_day} onChange={(e) => updateTerm({ ...term, max_per_day: Number(e.target.value) })} /></label>
            </div>
            <p className="text-sm text-gray-600">Weekends are always excluded.</p>
            {term.holidays.map((holiday, index) => (
              <div key={index} className="flex flex-wrap gap-2 items-end">
                <label className="text-sm">No school on<input className={inputClass} type="date" required min={term.term_start} max={term.term_end} value={holiday.date} onChange={(e) => updateTerm({ ...term, holidays: term.holidays.map((h, i) => (i === index ? { ...h, date: e.target.value } : h)) })} /></label>
                <label className="text-sm flex-1 min-w-[10rem]">Reason<input className={inputClass} required maxLength={120} value={holiday.label} onChange={(e) => updateTerm({ ...term, holidays: term.holidays.map((h, i) => (i === index ? { ...h, label: e.target.value } : h)) })} /></label>
                <button type="button" className="px-3 py-2 text-sm text-red-700" onClick={() => updateTerm({ ...term, holidays: term.holidays.filter((_, i) => i !== index) })}>Remove</button>
              </div>
            ))}
            <div className="flex gap-3">
              <button type="button" className="border rounded-lg px-3 py-2 text-sm" onClick={() => updateTerm({ ...term, holidays: [...term.holidays, { date: '', label: '' }] })}>Add a day off</button>
              <button type="submit" disabled={!dirty} className="bg-black text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40">Save settings</button>
            </div>
          </fieldset>
          {messageAt('term')}
        </form>
      </Section>

      <Section id="scheduler-build" title="Build the calendar" open={open.build} onToggle={() => toggle('build')}
        subtitle="Draft events from the dates in your documents and assignments; they wait in Approvals.">
        <div className="flex flex-wrap gap-3 items-center">
          <button type="button" onClick={draft} disabled={busy || loading || !saved || dirty}
            className="inline-flex items-center gap-1.5 bg-black text-white rounded-lg px-4 py-2 text-sm disabled:opacity-40">
            <Wand2 className="w-4 h-4" /> {busy ? 'Working…' : 'Draft from documents'}
          </button>
          <button type="button" onClick={() => setShowAi((v) => !v)} className="inline-flex items-center gap-1.5 text-sm text-gray-700 underline">
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
              <textarea className={`${inputClass} mt-1 font-normal`} value={instruction} onChange={(e) => setInstruction(e.target.value)} />
            </label>
            <button type="button" className="border border-gray-900 rounded-lg px-4 py-2 text-sm disabled:opacity-40" disabled={busy || loading || !saved || dirty || !instruction.trim()} onClick={buildWithAi}>Build with AI</button>
            <p className="text-xs text-gray-500">Uses the scheduler's model (needs its API key in the scheduler .env).</p>
          </div>
        )}
        {!saved && !loading && <p className="text-sm text-amber-700">Save the term settings first.</p>}
        {dirty && <p className="text-sm text-amber-700">Save your settings before building.</p>}
        {messageAt('build')}
        {skipped.length > 0 && (
          <div className="bg-amber-50 text-amber-950 rounded-lg p-3">
            <h3 className="font-medium text-sm">Needs your call ({skipped.length})</h3>
            <p className="text-xs text-amber-900 mb-2">These dates were found but break a rule, so they weren't drafted. Add them on the calendar on a different day, or change the rules.</p>
            <ul className="text-sm space-y-1">
              {skipped.map((s, i) => (
                <li key={i}>
                  <button type="button" className="underline decoration-dotted" onClick={() => showDay(s.date)}>
                    {shortDate(s.date)}
                  </button>{' '}· {s.title} <span className="text-amber-800">({kindLabel(s.kind)}: {s.problem})</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      <Section id="scheduler-suggest" title="Suggest check-ins" open={open.suggest} onToggle={() => toggle('suggest')}
        subtitle="A lesson day for each Library unit's check-in; draft the ones you want in one go.">
        <SuggestCheckins key={classId} classId={classId} term={calendarTerm} open={open.suggest}
          onDrafted={refresh} onOpenApprovals={onOpenApprovals} onShowDay={showDay} />
      </Section>
    </AgentPanelShell>
  );
};

export default SchedulerPanel;
