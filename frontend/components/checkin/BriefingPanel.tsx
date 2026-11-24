import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, ChevronDown, ClipboardCopy, Lightbulb, Loader2, Lock, Pencil, Plus, RefreshCw, Search, Sparkles, Users, X,
} from 'lucide-react';
import {
  generateWarmup, getBriefing, listCheckins, runMisconceptionFinder, saveWarmup,
  type Briefing, type CheckinStage, type CheckinSummary, type HelpLevel, type RosterEntry, type StudentStruggles, type Warmup,
} from '../../services/agentsApi';
import {
  STAGE_LABEL, STAGE_STYLE, formatDay, formatDue, isoDay, pct, rememberBriefingCheckin, rememberedBriefingCheckin, tutorModeLabel,
} from './format';

const STAGES: CheckinStage[] = ['not_started', 'practicing', 'checkin', 'complete'];
const card = 'bg-white rounded-xl border border-gray-200 p-4 sm:p-5';
const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

const HELP: Record<HelpLevel, { label: string; style: string }> = {
  none: { label: 'No tutor help', style: 'bg-gray-100 text-gray-700' },
  hint: { label: 'Needed hints', style: 'bg-amber-100 text-amber-900' },
  explained: { label: 'Tutor explained it', style: 'bg-rose-100 text-rose-900' },
};

/** The upcoming (or today's) lesson first, otherwise the most recent check-in. */
function defaultCheckin(list: CheckinSummary[], remembered: number | null): number | null {
  if (remembered && list.some((c) => c.assignment_id === remembered)) return remembered;
  const today = isoDay(new Date());
  const upcoming = list
    .filter((c) => c.lesson_date && c.lesson_date.slice(0, 10) >= today)
    .sort((a, b) => a.lesson_date!.localeCompare(b.lesson_date!));
  return (upcoming[0] ?? list[0])?.assignment_id ?? null;
}

const Bar: React.FC<{ value: number; marker?: number; tone?: string; label: string }> = ({ value, marker, tone = 'bg-gray-900', label }) => (
  <div className="relative h-2 w-full rounded-full bg-gray-100" role="meter" aria-label={label}
    aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}>
    <div className={`h-2 rounded-full ${tone}`} style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    {marker != null && (
      <div className="absolute -top-0.5 h-3 w-0.5 bg-gray-500" style={{ left: `calc(${Math.min(1, marker) * 100}% - 1px)` }}
        title={`Unlocks at ${pct(marker)}`} aria-hidden="true" />
    )}
  </div>
);

const SectionTitle: React.FC<{ icon: React.ReactNode; title: string; children?: React.ReactNode }> = ({ icon, title, children }) => (
  <div className="flex flex-wrap items-center justify-between gap-2">
    <h3 className="flex items-center gap-2 font-semibold text-gray-900">{icon}{title}</h3>
    {children}
  </div>
);

// ---- 1. Who's where ------------------------------------------------------------------------

const RosterRow: React.FC<{ s: RosterEntry; threshold: number }> = ({ s, threshold }) => {
  const right = s.stage === 'not_started' ? 'Not started'
    : s.stage === 'practicing' ? `${pct(s.mastery)} practiced`
    : `${s.resolved} of ${s.total} done`;
  return (
    <li className="flex items-center gap-3 py-1.5">
      <span className="w-24 sm:w-32 shrink-0 truncate text-sm text-gray-900" title={s.name}>{s.name}</span>
      <span className="flex-1 min-w-0">
        {s.stage === 'not_started' ? <span className="block h-2 rounded-full bg-gray-100" />
          : s.stage === 'practicing' ? <Bar value={s.mastery} marker={threshold} tone="bg-amber-500" label={`${s.name} practice mastery`} />
          : <Bar value={s.total ? s.resolved / s.total : 0} tone={s.stage === 'complete' ? 'bg-emerald-500' : 'bg-sky-500'} label={`${s.name} check-in progress`} />}
      </span>
      <span className="w-24 shrink-0 text-right text-xs text-gray-600">{right}</span>
    </li>
  );
};

const WhosWhere: React.FC<{ b: Briefing }> = ({ b }) => (
  <section className={`${card} space-y-4`}>
    <SectionTitle icon={<Users className="w-4 h-4" aria-hidden="true" />} title="Who's where" />
    <ul className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      {STAGES.map((st) => (
        <li key={st} className={`rounded-lg border px-3 py-2 ${STAGE_STYLE[st].tile}`}>
          <span className="block text-2xl font-semibold leading-tight">{b.counts[st]}</span>
          <span className="text-xs">{STAGE_LABEL[st]}</span>
        </li>
      ))}
    </ul>
    {b.roster.length === 0 ? <p className="text-sm text-gray-600">No students are enrolled in this class yet.</p> : (
      <div className="space-y-3">
        {[...STAGES].reverse().map((st) => {
          const group = b.roster.filter((s) => s.stage === st);
          if (!group.length) return null;
          return (
            <div key={st}>
              <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-gray-500">
                <span className={`w-2 h-2 rounded-full ${STAGE_STYLE[st].dot}`} aria-hidden="true" />{STAGE_LABEL[st]} · {group.length}
              </p>
              <ul className="divide-y divide-gray-50">
                {group.map((s) => <RosterRow key={s.student_id} s={s} threshold={b.assignment.mastery_threshold} />)}
              </ul>
            </div>
          );
        })}
        <p className="text-xs text-gray-500">Practice bars show cards mastered; the tick is where the check-in unlocks ({pct(b.assignment.mastery_threshold)}).</p>
      </div>
    )}
  </section>
);

// ---- 2. Class misconceptions ---------------------------------------------------------------

const Misconceptions: React.FC<{ b: Briefing; classId: number; onChanged: () => void }> = ({ b, classId, onChanged }) => {
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const run = async () => {
    setBusy(true); setNotice(''); setError('');
    try {
      const r = await runMisconceptionFinder(classId, b.assignment.assignment_id);
      const held = r.insights_suppressed ? ` ${r.insights_suppressed} weaker pattern(s) held back until more students show them.` : '';
      setNotice(`Read ${r.questions_analyzed} tutor conversation(s); found ${r.insights_found} misconception(s).${held}`);
      onChanged();
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  };
  return (
    <section className={`${card} space-y-4`}>
      <SectionTitle icon={<Lightbulb className="w-4 h-4" aria-hidden="true" />} title="Class misconceptions">
        <button type="button" onClick={run} disabled={busy}
          className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <Search className="w-4 h-4" aria-hidden="true" />}
          {busy ? 'Reading chats…' : 'Find misconceptions in tutor chats'}
        </button>
      </SectionTitle>
      <div aria-live="polite">
        {notice && <p className="text-sm text-emerald-800">{notice}</p>}
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      </div>
      {b.misconceptions.length === 0 ? (
        <p className="text-sm text-gray-600">
          None yet. Run the finder once students have chatted with the tutor (it uses the local model, and names are masked first).
        </p>
      ) : (
        <ul className="space-y-3">
          {b.misconceptions.map((m) => (
            <li key={m.insight_id} className="rounded-lg border border-gray-200 p-3 space-y-1.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                <p className="font-medium text-gray-900 break-words">{m.topic}</p>
                <p className="text-xs text-gray-500">{m.evidence_count} conversation(s) · {m.suggestion.supporting_student_count ?? 'several'} students</p>
              </div>
              {m.suggestion.explanation && <p className="text-sm text-gray-700 break-words">{m.suggestion.explanation}</p>}
              {m.suggestion.reteaching_activity && <p className="text-sm text-gray-700 break-words"><span className="font-medium">Reteach:</span> {m.suggestion.reteaching_activity}</p>}
              {m.model_used?.startsWith('offline:') && <p className="text-xs text-amber-700">Offline demonstration (keyword grouping, not model analysis).</p>}
              {m.examples.length > 0 && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-gray-600">Anonymized examples</summary>
                  <ul className="mt-1 space-y-1">{m.examples.map((ex, i) => <li key={i} className="border-l-2 border-gray-300 pl-2 text-gray-600 break-words">{ex}</li>)}</ul>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <h4 className="text-sm font-semibold text-gray-900">Hardest check-in questions</h4>
          {b.hardest_questions.length === 0 ? <p className="mt-1 text-sm text-gray-600">No answers yet.</p> : (
            <ol className="mt-2 space-y-2.5">
              {b.hardest_questions.slice(0, 5).map((q) => (
                <li key={q.question_id} className="text-sm">
                  <p className="text-gray-900 break-words"><span className="font-semibold">Q{q.number}.</span> {q.text}</p>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="flex-1 min-w-0"><Bar value={q.first_try_rate} tone={q.first_try_rate < 0.5 ? 'bg-rose-500' : q.first_try_rate < 0.8 ? 'bg-amber-500' : 'bg-emerald-500'} label={`Q${q.number} right first try`} /></span>
                    <span className="shrink-0 text-xs text-gray-600">{q.answered - q.misses}/{q.answered} right first try</span>
                  </div>
                  {(q.explained > 0 || q.still_open > 0) && (
                    <p className="mt-0.5 text-xs text-gray-500">
                      {q.explained > 0 && `Tutor had to explain it ${q.explained}×`}{q.explained > 0 && q.still_open > 0 && ' · '}
                      {q.still_open > 0 && `${q.still_open} still working on it`}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
        <div>
          <h4 className="text-sm font-semibold text-gray-900">Most-missed practice cards</h4>
          {b.hardest_items.length === 0 ? <p className="mt-1 text-sm text-gray-600">No missed cards yet.</p> : (
            <ul className="mt-2 space-y-2">
              {b.hardest_items.slice(0, 6).map((it) => (
                <li key={`${it.activity_id}:${it.item_id}`} className="text-sm">
                  <p className="text-gray-900 break-words">{it.label}{it.answer && <span className="text-gray-500"> → {it.answer}</span>}</p>
                  <p className="text-xs text-gray-500">Missed {it.misses}× by {it.students} student(s){it.still_missing > 0 && ` · ${it.still_missing} still missing it`}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
};

// ---- 3. Per-student struggles --------------------------------------------------------------

function struggleSummary(s: StudentStruggles): string {
  if (s.stage === 'not_started') return "Hasn't started";
  if (s.stage === 'practicing') return `Practicing · ${Math.round(s.signals.practice_mastery)}% of cards`;
  const open = s.missed.filter((m) => m.status === 'needs_fix').length;
  if (!s.missed.length) return `${s.signals.answered} of ${s.signals.total} answered · no misses`;
  return `${s.missed.length} missed${open ? ` · ${open} still open` : ' · all fixed'}`;
}

const StudentRow: React.FC<{ s: StudentStruggles; open: boolean; onToggle: () => void }> = ({ s, open, onToggle }) => {
  const sig = s.signals;
  const id = `struggles-${s.student_id}`;
  return (
    <li className="py-2">
      <button type="button" onClick={onToggle} aria-expanded={open} aria-controls={id}
        className="w-full flex items-center gap-2 text-left">
        <span className={`w-2 h-2 rounded-full shrink-0 ${STAGE_STYLE[s.stage].dot}`} aria-hidden="true" />
        <span className="font-medium text-sm text-gray-900 truncate">{s.name}</span>
        <span className="flex-1 min-w-0 truncate text-xs text-gray-600 text-right">{struggleSummary(s)}</span>
        <ChevronDown className={`w-4 h-4 shrink-0 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {open && (
        <div id={id} className="mt-2 ml-4 space-y-3">
          <dl className="flex flex-wrap gap-2 text-xs">
            {([
              ['Practice', `${Math.round(sig.practice_mastery)}%`],
              ['Right first try', sig.first_try_accuracy == null ? '–' : `${Math.round(sig.first_try_accuracy)}%`],
              ['Misses fixed', sig.fixed_with_help == null ? '–' : `${Math.round(sig.fixed_with_help)}%`],
              ['Done', `${sig.resolved}/${sig.total}`],
            ] as const).map(([k, v]) => (
              <div key={k} className="rounded-md bg-gray-50 border border-gray-100 px-2 py-1"><dt className="inline text-gray-500">{k} </dt><dd className="inline font-medium text-gray-900">{v}</dd></div>
            ))}
          </dl>
          {s.missed.length === 0 ? <p className="text-sm text-gray-600">No missed questions.</p> : (
            <ul className="space-y-2.5">
              {s.missed.map((m) => (
                <li key={m.question_id} className="rounded-lg border border-gray-200 p-3 text-sm space-y-1">
                  <p className="text-gray-900 break-words"><span className="font-semibold">Q{m.number}.</span> {m.text}</p>
                  {m.first_answer && <p className="text-gray-600 break-words"><span className="text-gray-500">First answer:</span> {m.first_answer}</p>}
                  <p className="flex flex-wrap gap-1.5">
                    <span className={`text-xs rounded-full px-2 py-0.5 ${HELP[m.help_level]?.style ?? HELP.none.style}`}>{HELP[m.help_level]?.label ?? m.help_level}</span>
                    <span className={`text-xs rounded-full px-2 py-0.5 ${m.status === 'fixed' ? 'bg-emerald-100 text-emerald-900' : 'bg-sky-100 text-sky-900'}`}>
                      {m.status === 'fixed' ? 'Fixed' : `Still open${m.tries ? ` · ${m.tries} tr${m.tries === 1 ? 'y' : 'ies'}` : ''}`}
                    </span>
                  </p>
                  {m.explain_back && (
                    <blockquote className="border-l-2 border-gray-300 pl-2 text-gray-700 italic break-words">
                      {m.status === 'fixed' ? 'In their words: ' : 'Latest try: '}“{m.explain_back}”
                    </blockquote>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
};

const Struggles: React.FC<{ b: Briefing }> = ({ b }) => {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const students = useMemo(() => [...b.students].sort((x, y) => {
    const score = (s: StudentStruggles) => s.missed.filter((m) => m.status === 'needs_fix' || m.help_level === 'explained').length * 10 + s.missed.length;
    return score(y) - score(x) || x.name.localeCompare(y.name);
  }), [b.students]);
  const withMisses = students.filter((s) => s.missed.length > 0);
  const toggle = (id: number) => setOpen((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  return (
    <section className={`${card} space-y-2`}>
      <SectionTitle icon={<Lock className="w-4 h-4" aria-hidden="true" />} title="Per-student struggles">
        {withMisses.length > 0 && (
          <button type="button" className="text-sm text-gray-600 underline"
            onClick={() => setOpen((cur) => (cur.size ? new Set() : new Set(withMisses.map((s) => s.student_id))))}>
            {open.size ? 'Collapse all' : 'Expand students with misses'}
          </button>
        )}
      </SectionTitle>
      <p className="text-xs text-gray-500">Only you see this. Misses never lower the grade; it's what to check on in class.</p>
      {students.length === 0 ? <p className="text-sm text-gray-600">No students yet.</p> : (
        <ul className="divide-y divide-gray-100">
          {students.map((s) => <StudentRow key={s.student_id} s={s} open={open.has(s.student_id)} onToggle={() => toggle(s.student_id)} />)}
        </ul>
      )}
    </section>
  );
};

// ---- 4. Suggested warm-up ------------------------------------------------------------------

const WarmupSection: React.FC<{ b: Briefing; classId: number; onSaved: (w: Warmup) => void }> = ({ b, classId, onSaved }) => {
  const w = b.warmup;
  const aid = b.assignment.assignment_id;
  const [busy, setBusy] = useState<'' | 'model' | 'offline' | 'save'>('');
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const [draftQs, setDraftQs] = useState<string[]>([]);
  const [draftReteach, setDraftReteach] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => { setEditing(false); setError(''); }, [aid]);

  const generate = async (offline: boolean) => {
    if (w?.edited && !window.confirm('Replace your edited warm-up with a new suggestion?')) return;
    setBusy(offline ? 'offline' : 'model'); setError('');
    try { onSaved(await generateWarmup(classId, aid, offline)); setEditing(false); } catch (e) { setError(errText(e)); } finally { setBusy(''); }
  };
  const startEdit = () => {
    setDraftQs(w?.questions.length ? [...w.questions] : ['']);
    setDraftReteach(w?.reteach ?? '');
    setEditing(true);
  };
  const cleanQs = draftQs.map((q) => q.trim()).filter(Boolean);
  const save = async () => {
    if (!cleanQs.length || !draftReteach.trim()) return;
    setBusy('save'); setError('');
    try { onSaved(await saveWarmup(classId, aid, { questions: cleanQs, reteach: draftReteach.trim() })); setEditing(false); }
    catch (e) { setError(errText(e)); } finally { setBusy(''); }
  };
  const copy = async () => {
    if (!w) return;
    const text = `${w.questions.map((q, i) => `${i + 1}. ${q}`).join('\n')}\n\n${w.reteach}`;
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch { /* clipboard blocked */ }
  };

  return (
    <section className={`${card} space-y-3`}>
      <SectionTitle icon={<Sparkles className="w-4 h-4" aria-hidden="true" />} title="Suggested warm-up">
        {w && !editing && (
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={copy} className="inline-flex items-center gap-1 text-sm px-2.5 py-1 rounded-lg border border-gray-300 hover:bg-gray-50">
              <ClipboardCopy className="w-4 h-4" aria-hidden="true" />{copied ? 'Copied' : 'Copy'}
            </button>
            <button type="button" onClick={startEdit} className="inline-flex items-center gap-1 text-sm px-2.5 py-1 rounded-lg border border-gray-300 hover:bg-gray-50">
              <Pencil className="w-4 h-4" aria-hidden="true" />Edit
            </button>
          </div>
        )}
      </SectionTitle>
      <p className="text-xs text-gray-500">3-5 minutes at the start of class, built from the hardest questions and the top misconception.</p>

      {editing ? (
        <div className="space-y-3">
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-gray-700">On the board</legend>
            {draftQs.map((q, i) => (
              <div key={i} className="flex gap-2">
                <input value={q} maxLength={500} aria-label={`Board question ${i + 1}`}
                  onChange={(e) => setDraftQs((cur) => cur.map((x, j) => (j === i ? e.target.value : x)))}
                  className="flex-1 min-w-0 rounded-lg border border-gray-300 px-3 py-2 text-sm" />
                {draftQs.length > 1 && (
                  <button type="button" aria-label={`Remove question ${i + 1}`} onClick={() => setDraftQs((cur) => cur.filter((_, j) => j !== i))}
                    className="p-2 text-gray-400 hover:text-red-600"><X className="w-4 h-4" aria-hidden="true" /></button>
                )}
              </div>
            ))}
            {draftQs.length < 5 && (
              <button type="button" onClick={() => setDraftQs((cur) => [...cur, ''])} className="inline-flex items-center gap-1 text-sm text-gray-700 underline">
                <Plus className="w-4 h-4" aria-hidden="true" />Add a question
              </button>
            )}
          </fieldset>
          <label className="block text-sm font-medium text-gray-700">Reteach
            <textarea value={draftReteach} onChange={(e) => setDraftReteach(e.target.value)} rows={3} maxLength={1500}
              className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={save} disabled={busy === 'save' || !cleanQs.length || !draftReteach.trim()}
              className="px-4 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium disabled:opacity-50">
              {busy === 'save' ? 'Saving…' : 'Save warm-up'}
            </button>
            <button type="button" onClick={() => setEditing(false)} className="px-4 py-2 rounded-lg border border-gray-300 text-sm">Cancel</button>
          </div>
        </div>
      ) : w ? (
        <div className="space-y-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-gray-500">On the board</p>
            <ol className="mt-1 list-decimal pl-5 space-y-1 text-gray-900">
              {w.questions.map((q, i) => <li key={i} className="break-words">{q}</li>)}
            </ol>
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-gray-500">Reteach</p>
            <p className="mt-1 text-gray-900 break-words">{w.reteach}</p>
          </div>
          {w.based_on.length > 0 && (
            <p className="flex flex-wrap gap-1.5 text-xs">
              <span className="text-gray-500">Based on</span>
              {w.based_on.map((x) => (
                <span key={x.kind === 'question' ? `q${x.question_id}` : `m${x.insight_id}`} className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-700">
                  {x.kind === 'question' ? `Q${x.number} · ${pct(x.first_try_rate)} right first try` : `Mix-up: ${x.topic}`}
                </span>
              ))}
            </p>
          )}
          <p className="text-xs text-gray-500">
            {w.model_used === 'deterministic' ? 'Built without AI from the check-in results' : w.model_used === 'teacher' ? 'Written by you' : `Drafted by ${w.model_used}`}
            {w.edited && ' · edited by you'}
          </p>
        </div>
      ) : (
        <p className="text-sm text-gray-600">No warm-up yet.</p>
      )}

      {!editing && (
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => generate(false)} disabled={!!busy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-900 text-white text-sm font-medium disabled:opacity-50">
            {busy === 'model' ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <Sparkles className="w-4 h-4" aria-hidden="true" />}
            {busy === 'model' ? 'Thinking…' : w ? 'Suggest a new one' : 'Suggest a warm-up'}
          </button>
          <button type="button" onClick={() => generate(true)} disabled={!!busy}
            className="px-3 py-1.5 rounded-lg border border-gray-300 text-sm disabled:opacity-50">
            {busy === 'offline' ? 'Building…' : 'Quick, without AI'}
          </button>
          {!w && <button type="button" onClick={startEdit} className="px-3 py-1.5 rounded-lg border border-gray-300 text-sm">Write my own</button>}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </section>
  );
};

// ---- The panel ------------------------------------------------------------------------------

/**
 * The before-class briefing for one unit check-in: who's where, class misconceptions,
 * per-student struggles and a suggested warm-up. Meant to be read the morning of the lesson.
 */
const BriefingPanel: React.FC<{ classId: number; onInsightsChanged?: () => void }> = ({ classId, onInsightsChanged }) => {
  const [checkins, setCheckins] = useState<CheckinSummary[] | null>(null);
  const [listError, setListError] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setCheckins(null); setListError(''); setSelected(null); setBriefing(null);
    listCheckins(classId, controller.signal)
      .then((r) => {
        if (controller.signal.aborted) return;
        setCheckins(r.checkins);
        setSelected(defaultCheckin(r.checkins, rememberedBriefingCheckin(classId)));
      })
      .catch((e) => { if (!controller.signal.aborted) setListError(errText(e)); });
    return () => controller.abort();
  }, [classId]);

  useEffect(() => {
    if (selected == null) return;
    const controller = new AbortController();
    setLoading(true); setError('');
    getBriefing(classId, selected, controller.signal)
      .then((b) => { if (!controller.signal.aborted) { setBriefing(b); setLoadedAt(new Date()); } })
      .catch((e) => { if (!controller.signal.aborted) setError(errText(e)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [classId, selected, reloadKey]);

  const choose = (id: number) => {
    setSelected(id);
    setBriefing(null);
    rememberBriefingCheckin(classId, id);
  };
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  const insightsChanged = useCallback(() => { reload(); onInsightsChanged?.(); }, [reload, onInsightsChanged]);
  const a = briefing?.assignment;

  return (
    <div className="space-y-4">
      <div className={`${card} space-y-3`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-gray-900">Before-class briefing</h2>
            <p className="text-sm text-gray-600">What the check-in showed, for the start of the lesson.</p>
          </div>
          {selected != null && (
            <button type="button" onClick={reload} disabled={loading}
              className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" /> Refresh
            </button>
          )}
        </div>
        {listError ? (
          <p role="alert" className="text-sm text-red-700">Couldn't load check-ins: {listError}</p>
        ) : checkins === null ? (
          <p className="text-sm text-gray-500 inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Loading check-ins…</p>
        ) : checkins.length === 0 ? (
          <p className="text-sm text-gray-600 rounded-lg bg-gray-50 border border-gray-200 p-3">
            No unit check-ins yet. Create one from Assignments → New unit check-in; once it's approved, its briefing appears here.
          </p>
        ) : (
          <label className="block text-sm font-medium text-gray-700">Check-in
            <select className="mt-1 block w-full sm:max-w-md rounded-lg border border-gray-300 p-2 text-sm"
              value={selected ?? ''} onChange={(e) => choose(Number(e.target.value))}>
              {checkins.map((c) => (
                <option key={c.assignment_id} value={c.assignment_id}>
                  {c.title}{c.lesson_date ? ` · lesson ${formatDay(c.lesson_date)}` : ''}
                </option>
              ))}
            </select>
          </label>
        )}
        {a && (
          <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-600">
            {a.unit && <span>{a.unit}</span>}
            {a.lesson_date && <span>Lesson {formatDay(a.lesson_date)}</span>}
            {a.due_date && <span className={a.past_due ? 'text-gray-900 font-medium' : ''}>{a.past_due ? 'Was due' : 'Due'} {formatDue(a.due_date)}</span>}
            <span>{tutorModeLabel(a.tutor_mode, a.tutor_reveal_after)}</span>
            <span>{a.question_count} questions · {a.item_count} practice cards</span>
            {loadedAt && <span>Updated {loadedAt.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</span>}
          </p>
        )}
      </div>

      {error && (
        <div role="alert" className={`${card} flex flex-wrap items-center gap-3 text-sm text-red-700`}>
          <AlertTriangle className="w-4 h-4" aria-hidden="true" /> <span className="flex-1 min-w-0">{error}</span>
          <button type="button" onClick={reload} className="px-3 py-1.5 rounded-lg border border-red-200 hover:bg-red-50">Try again</button>
        </div>
      )}
      {loading && !briefing && (
        <p className="text-sm text-gray-500 inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Loading the briefing…</p>
      )}
      {briefing && (
        <>
          <WhosWhere b={briefing} />
          <Misconceptions b={briefing} classId={classId} onChanged={insightsChanged} />
          <Struggles b={briefing} />
          <WarmupSection b={briefing} classId={classId} onSaved={(w) => setBriefing((cur) => (cur ? { ...cur, warmup: w } : cur))} />
        </>
      )}
    </div>
  );
};

export default BriefingPanel;
