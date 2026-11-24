import React, { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Loader2, RefreshCw, Sparkles, XCircle } from 'lucide-react';
import { createUnitPackage, getAgentsHealth } from '../../../services/agentsApi';
import { getCheckinSuggestions, type CheckinSuggestion } from '../../../services/schedulerFeedApi';
import { eveningBefore, formatDay } from '../../checkin/format';
import { Term, dayOffReason, kindLabel, shortDate, todayISO } from './calendarUtils';

/**
 * "Suggest check-ins": the scheduler proposes a lesson day per Library unit (before its quiz or
 * test, say). The teacher adjusts the days, ticks the ones to keep, and drafts a unit package for
 * each, one after another. Drafts wait in Approvals; nothing reaches students until approved.
 */
interface Props {
  classId: number;
  term: Term | null;
  /** The section is open: load the suggestions the first time. */
  open: boolean;
  /** After drafting: refetch the calendar so the drafts show (dashed). */
  onDrafted: () => void;
  onOpenApprovals?: () => void;
  /** Show a day on the calendar. */
  onShowDay?: (day: string) => void;
}

type RowResult = { state: 'working' } | { state: 'ok'; packageId: number } | { state: 'error'; message: string };

interface Row extends CheckinSuggestion {
  key: string;
  lesson: string;
  due: string; // YYYY-MM-DD, due 23:59 local
  checked: boolean;
  result: RowResult | null;
}

// Same defaults as "New unit check-in".
const PACKAGE_DEFAULTS = { tutor_mode: 'hints_only' as const, tutor_reveal_after: 2, mastery_threshold: 0.8, mc_count: 4, explain_count: 2 };

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

const SuggestCheckins: React.FC<Props> = ({ classId, term, open, onDrafted, onOpenApprovals, onShowDay }) => {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [skipped, setSkipped] = useState<Array<{ unit: string; reason: string }>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [aiReady, setAiReady] = useState<boolean | null>(null);
  const [useAi, setUseAi] = useState(false);
  const [running, setRunning] = useState(false);
  const loaded = useRef(false);
  const today = todayISO();

  const problemOf = (row: Row): string | null => {
    if (!row.lesson) return 'Pick a lesson day.';
    if (row.lesson < today) return 'That day has passed.';
    const off = dayOffReason(row.lesson, term);
    return off ? `${off} Pick a school day.` : null;
  };

  const load = async () => {
    setLoading(true); setError('');
    try {
      const r = await getCheckinSuggestions(classId);
      setSkipped(r.skipped);
      setRows(r.suggestions.map((s, i) => {
        const row: Row = { ...s, key: `${s.unit}|${s.lesson_date}|${i}`, lesson: s.lesson_date, due: s.due_day, checked: true, result: null };
        return { ...row, checked: !problemOf(row) };
      }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open || loaded.current) return;
    loaded.current = true;
    load();
    getAgentsHealth()
      .then((h) => {
        const ready = !!h.agents.find((a) => a.name === 'games')?.ready;
        setAiReady(ready); setUseAi(ready);
      })
      .catch(() => { setAiReady(false); setUseAi(false); });
    // Loads once, when the section first opens (the parent remounts this per class).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const update = (key: string, patch: Partial<Row>) =>
    setRows((rs) => rs && rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const setLesson = (row: Row, lesson: string) => {
    const due = lesson ? eveningBefore(lesson).slice(0, 10) : row.due;
    const next = { ...row, lesson, due };
    // A day that becomes usable is ticked again; one that isn't can't stay ticked.
    update(row.key, { lesson, due, checked: problemOf(next) ? false : problemOf(row) ? true : row.checked });
  };

  const drafted = (rows ?? []).filter((r) => r.result?.state === 'ok').length;
  const selected = (rows ?? []).filter((r) => r.checked && r.result?.state !== 'ok' && !problemOf(r));

  const draftSelected = async () => {
    if (!selected.length || running) return;
    setRunning(true);
    let made = 0;
    for (const row of selected) {
      update(row.key, { result: { state: 'working' } });
      try {
        const dueDate = new Date(`${row.due}T23:59`);
        const res = await createUnitPackage({
          class_id: classId,
          unit: row.unit,
          lesson_date: row.lesson,
          ...(Number.isNaN(dueDate.getTime()) ? {} : { due_date: dueDate.toISOString(), due_day: row.due }),
          title: `${row.unit} practice + check-in`,
          ...PACKAGE_DEFAULTS,
          offline: !useAi,
        });
        made += 1;
        update(row.key, { result: { state: 'ok', packageId: res.package_id }, checked: false });
      } catch (e) {
        update(row.key, { result: { state: 'error', message: errorText(e) } });
      }
    }
    setRunning(false);
    if (made) onDrafted();
  };

  if (loading && !rows) {
    return <p className="text-sm text-gray-500 inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Looking for units to check in on…</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-gray-600">
          One check-in per Library unit, on the lesson before its quiz or test when there is one. Change a day, untick what
          you don't want, then draft. No AI is used to pick the days.
        </p>
        <button type="button" onClick={load} disabled={loading || running}
          className="inline-flex items-center gap-1.5 text-sm text-gray-700 underline disabled:opacity-40">
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" /> Refresh suggestions
        </button>
      </div>
      {error && <p role="alert" className="text-sm text-red-700">Couldn't load suggestions: {error}</p>}

      {rows && rows.length === 0 && !error && (
        <p className="text-sm text-gray-600 rounded-lg bg-gray-50 border border-gray-200 p-3">
          No suggestions right now: every unit already has a check-in, or there are no units in the Library yet.
        </p>
      )}

      {rows && rows.length > 0 && (
        <ul className="space-y-2">
          {rows.map((row) => {
            const problem = problemOf(row);
            const done = row.result?.state === 'ok';
            return (
              <li key={row.key} className={`rounded-xl border p-3 space-y-2 ${done ? 'border-emerald-200 bg-emerald-50/40' : 'border-gray-200'}`}>
                <div className="flex flex-col sm:flex-row sm:items-start gap-3">
                  <label className="flex-1 min-w-0 flex items-start gap-2 cursor-pointer">
                    <input type="checkbox" className="mt-1" checked={row.checked}
                      disabled={running || done || !!problem}
                      onChange={(e) => update(row.key, { checked: e.target.checked })} />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-gray-900 break-words">{row.unit}</span>
                      <span className="block text-xs text-gray-600 break-words">{row.reason}</span>
                      {row.anchor && (
                        <span className="block text-xs text-gray-500 break-words">
                          {row.anchor.title} ({kindLabel(row.anchor.kind).toLowerCase()}, {shortDate(row.anchor.date)})
                          {row.anchor.source === 'calendar' ? ', on the calendar' : row.anchor.source ? `, from ${row.anchor.source}` : ''}
                        </span>
                      )}
                    </span>
                  </label>
                  <div className="sm:w-52 shrink-0 space-y-1">
                    <label className="block text-xs text-gray-600">Lesson day
                      <input type="date" value={row.lesson} disabled={running || done}
                        min={term?.term_start || undefined} max={term?.term_end || undefined}
                        onChange={(e) => setLesson(row, e.target.value)}
                        className="mt-0.5 block w-full rounded-lg border border-gray-300 px-2 py-1 text-sm disabled:bg-gray-50" />
                    </label>
                    <p className="text-xs text-gray-500">Due {formatDay(row.due)}, 11:59 PM</p>
                    {onShowDay && row.lesson && (
                      <button type="button" className="text-xs underline text-gray-700" onClick={() => onShowDay(row.lesson)}>Show on calendar</button>
                    )}
                  </div>
                </div>
                {problem && !done && <p className="text-xs text-amber-800">{problem}</p>}
                {row.result?.state === 'working' && (
                  <p className="text-xs text-gray-600 inline-flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> Drafting{useAi ? ' with AI (up to a minute)' : ''}…</p>
                )}
                {row.result?.state === 'ok' && (
                  <p className="text-xs text-emerald-800 inline-flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5" aria-hidden="true" /> Drafted: waiting for approval (dashed on the calendar).</p>
                )}
                {row.result?.state === 'error' && (
                  <p role="alert" className="text-xs text-red-700 inline-flex items-start gap-1.5"><XCircle className="w-3.5 h-3.5 mt-px shrink-0" aria-hidden="true" /> {row.result.message}</p>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {skipped.length > 0 && (
        <div className="text-sm">
          <h4 className="font-medium text-gray-700">Not suggested ({skipped.length})</h4>
          <ul className="mt-1 space-y-0.5 text-xs text-gray-600">
            {skipped.map((s, i) => <li key={`${s.unit}-${i}`}><span className="text-gray-800">{s.unit}</span>: {s.reason}</li>)}
          </ul>
        </div>
      )}

      {rows && rows.length > 0 && (
        <div className="space-y-2">
          {aiReady ? (
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input type="checkbox" checked={useAi} disabled={running} onChange={(e) => setUseAi(e.target.checked)} />
              <Sparkles className="w-4 h-4" aria-hidden="true" /> Use AI to write the games and questions (slower: up to a minute each)
            </label>
          ) : aiReady === false ? (
            <p className="text-xs text-gray-500">No API key for the games agent: drafts are built without AI from each unit's text. Review them closely.</p>
          ) : null}
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={draftSelected} disabled={running || selected.length === 0}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-800 disabled:opacity-40">
              {running && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
              {running ? 'Drafting…' : `Draft ${selected.length} check-in${selected.length === 1 ? '' : 's'}`}
            </button>
            {drafted > 0 && (
              <p role="status" className="text-sm text-emerald-800">
                {drafted} draft{drafted === 1 ? ' is' : 's are'} waiting for approval.{' '}
                {onOpenApprovals && <button type="button" className="underline font-medium" onClick={onOpenApprovals}>Open Approvals</button>}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default SuggestCheckins;
