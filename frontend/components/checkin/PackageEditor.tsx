import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { AlertTriangle, Check, Loader2, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import type { TutorMode } from '../../services/agentsApi';
import {
  regeneratePackagePart,
  updateUnitPackage,
  type EditableItem,
  type EditableQuestion,
  type EditedPackage,
  type PackageEdit,
  type PackageSettingsEdit,
  type PackageWarning,
  type RegenerateTarget,
} from '../../services/packageApi';
import { GAME_LABEL, eveningBefore, isoDay } from './format';

// ---------------------------------------------------------------- the local draft
const ITEM_FIELDS: Record<string, [string, string]> = {
  flashcards: ['front', 'back'],
  matching: ['term', 'definition'],
  fill_in: ['sentence', 'answer'],
};
const FIELD_LABEL: Record<string, string> = {
  front: 'Front', back: 'Back', term: 'Term', definition: 'Definition', sentence: 'Sentence', answer: 'Answer',
};
const ITEM_NOUN: Record<string, string> = { flashcards: 'Card', matching: 'Pair', fill_in: 'Sentence' };
const MAX_OPTIONS = 6;
const MIN_PRACTICE = 4;

interface DraftOption { key: string; text: string; correct: boolean }
interface DraftQuestion {
  key: string;
  kind: 'choice' | 'explain';
  text: string;
  options: DraftOption[];
  answer: string;
  rubric: string;
  source?: string;
}
interface DraftItem { key: string; item_id?: string; a: string; b: string; alternates: string; source?: string }
interface DraftActivity { key: string; activity_id: number; kind: string; title: string; items: DraftItem[] }
interface DraftSettings {
  title: string;
  lesson_date: string;
  due_local: string;           // datetime-local value in the teacher's time zone
  tutor_mode: TutorMode;
  reveal_after: number;
  threshold: number;           // percent
}
interface Draft { questions: DraftQuestion[]; activities: DraftActivity[]; settings: DraftSettings }

let seq = 0;
const newKey = () => `pk${++seq}`;
const pad = (n: number) => String(n).padStart(2, '0');
const blankFixed = (s: string) => s.replace(/_{3,}/g, '____');

function toLocalInput(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : `${isoDay(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function field(item: EditableItem, name: string): string {
  const v = (item as unknown as Record<string, unknown>)[name];
  return typeof v === 'string' ? v : '';
}

/** The package as an editable draft, plus the server's warnings keyed by the draft's row keys. */
function buildDraft(pkg: EditedPackage, warnings: PackageWarning[]): { draft: Draft; warn: Record<string, string[]> } {
  const warn: Record<string, string[]> = {};
  const note = (key: string, w: PackageWarning) => { (warn[key] ??= []).push(w.note); };
  const questions: DraftQuestion[] = pkg.questions.map((q, i) => {
    const key = newKey();
    warnings.filter((w) => w.target === 'question' && w.index === i).forEach((w) => note(key, w));
    return {
      key,
      kind: q.kind === 'explain' ? 'explain' : 'choice',
      text: q.text ?? '',
      options: (q.options ?? []).map((o) => ({ key: newKey(), text: o.text ?? '', correct: !!o.correct })),
      answer: q.answer ?? '',
      rubric: q.rubric ?? '',
      source: q.source,
    };
  });
  const activities: DraftActivity[] = pkg.activities.filter((a) => ITEM_FIELDS[a.kind]).map((a) => {
    const key = newKey();
    warnings.filter((w) => w.target === 'activity' && w.activity_id === a.activity_id).forEach((w) => note(key, w));
    const [fa, fb] = ITEM_FIELDS[a.kind];
    return {
      key,
      activity_id: a.activity_id,
      kind: a.kind,
      title: a.title,
      items: (a.items as EditableItem[]).map((it) => {
        const itemKey = newKey();
        warnings.filter((w) => w.target === 'item' && w.activity_id === a.activity_id && w.item_id === it.item_id)
          .forEach((w) => note(itemKey, w));
        return {
          key: itemKey, item_id: it.item_id, a: field(it, fa), b: field(it, fb),
          alternates: (it.alternates ?? []).join(', '), source: it.source,
        };
      }),
    };
  });
  const s = pkg.settings ?? {};
  return {
    warn,
    draft: {
      questions,
      activities,
      settings: {
        title: typeof s.title === 'string' ? s.title : '',
        lesson_date: typeof s.lesson_date === 'string' ? s.lesson_date.slice(0, 10) : '',
        due_local: toLocalInput(typeof s.due_date === 'string' ? s.due_date : ''),
        tutor_mode: s.tutor_mode === 'answer_after_tries' ? 'answer_after_tries' : 'hints_only',
        reveal_after: typeof s.tutor_reveal_after === 'number' ? s.tutor_reveal_after : 2,
        threshold: typeof s.mastery_threshold === 'number' ? Math.round(s.mastery_threshold * 100) : 80,
      },
    },
  };
}

/** Everything that matters for "unsaved changes" (row keys left out). */
function snapshot(d: Draft): string {
  return JSON.stringify({
    q: d.questions.map((q) => [q.kind, q.text, q.options.map((o) => [o.text, o.correct]), q.answer, q.rubric]),
    a: d.activities.map((a) => [a.activity_id, a.items.map((it) => [it.item_id ?? '', it.a, it.b, it.alternates])]),
    s: d.settings,
  });
}

function toEdit(d: Draft, base: Draft): PackageEdit {
  const questions: EditableQuestion[] = d.questions.map((q) => (q.kind === 'choice'
    ? { text: q.text.trim(), kind: 'choice', options: q.options.map((o) => ({ text: o.text.trim(), correct: o.correct })), source: q.source }
    : { text: q.text.trim(), kind: 'explain', answer: q.answer.trim(), rubric: q.rubric.trim(), source: q.source }));
  const activities = d.activities.map((a) => {
    const [fa, fb] = ITEM_FIELDS[a.kind];
    return {
      activity_id: a.activity_id,
      items: a.items.map((it) => {
        const out: Record<string, unknown> = { [fa]: it.a.trim(), [fb]: it.b.trim() };
        if (it.item_id) out.item_id = it.item_id;
        if (it.source) out.source = it.source;
        if (a.kind === 'fill_in') out.alternates = it.alternates.split(',').map((x) => x.trim()).filter(Boolean);
        return out as Partial<EditableItem>;
      }),
    };
  });
  const s = d.settings;
  const b = base.settings;
  const settings: PackageSettingsEdit = {};
  if (s.title !== b.title) settings.title = s.title.trim();
  if (s.lesson_date !== b.lesson_date) settings.lesson_date = s.lesson_date;
  // Always send the due date with a new lesson date, so the agent never resets it to its default.
  if ((s.due_local !== b.due_local || s.lesson_date !== b.lesson_date) && s.due_local) {
    const due = new Date(s.due_local);
    if (!Number.isNaN(due.getTime())) {
      settings.due_date = due.toISOString();
      settings.due_day = s.due_local.slice(0, 10);
    }
  }
  if (s.tutor_mode !== b.tutor_mode) settings.tutor_mode = s.tutor_mode;
  if (s.reveal_after !== b.reveal_after) settings.tutor_reveal_after = s.reveal_after;
  if (s.threshold !== b.threshold) settings.mastery_threshold = s.threshold / 100;
  return { questions, activities, ...(Object.keys(settings).length ? { settings } : {}) };
}

/** The agent's hard rules, checked as the teacher types (the agent checks them again on save). */
function validate(d: Draft): { byKey: Record<string, string[]>; global: string[] } {
  const byKey: Record<string, string[]> = {};
  const global: string[] = [];
  const need = (key: string, msg: string) => { (byKey[key] ??= []).push(msg); };
  if (d.questions.length === 0) global.push('Keep at least one check-in question.');
  for (const q of d.questions) {
    if (!q.text.trim()) need(q.key, 'write the question');
    if (q.kind === 'choice') {
      if (q.options.length < 2) need(q.key, 'at least 2 answer options');
      if (q.options.some((o) => !o.text.trim())) need(q.key, 'fill in every answer option');
      if (q.options.filter((o) => o.correct).length !== 1) need(q.key, 'mark the one right answer');
    } else if (!q.answer.trim()) {
      need(q.key, 'write a model answer');
    }
  }
  let total = 0;
  for (const a of d.activities) {
    total += a.items.length;
    const [fa, fb] = ITEM_FIELDS[a.kind];
    for (const it of a.items) {
      if (!it.a.trim() || !it.b.trim()) need(it.key, `fill in the ${FIELD_LABEL[fa].toLowerCase()} and the ${FIELD_LABEL[fb].toLowerCase()}`);
      if (a.kind === 'fill_in' && it.a.trim() && !blankFixed(it.a).includes('____')) need(it.key, 'mark the blank with ____');
    }
  }
  if (d.activities.length > 0 && total < MIN_PRACTICE) global.push(`Keep at least ${MIN_PRACTICE} practice cards across the games.`);
  const s = d.settings;
  if (!s.title.trim()) global.push('The title can\'t be empty.');
  if (!s.lesson_date) global.push('Pick the lesson date.');
  if (s.due_local && s.lesson_date && s.due_local.slice(0, 10) > s.lesson_date) global.push('The due date should be on or before the lesson.');
  return { byKey, global };
}

// ---------------------------------------------------------------- small pieces
const input = 'mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-400';
const smallBtn = 'inline-flex items-center gap-1 rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50';

const Notes: React.FC<{ needs?: string[]; warnings?: string[]; notice?: { text: string; tone: 'ok' | 'error' } }> = ({ needs, warnings, notice }) => (
  <>
    {needs && needs.length > 0 && (
      <p className="mt-2 text-xs text-red-700">Still needed: {needs.join('; ')}.</p>
    )}
    {warnings && warnings.length > 0 && (
      <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-800">
        <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden="true" />
        <span><span className="font-medium">Check:</span> {warnings.join('; ')}</span>
      </p>
    )}
    {notice && (
      <p className={`mt-2 text-xs ${notice.tone === 'error' ? 'text-red-700' : 'text-emerald-700'}`} role={notice.tone === 'error' ? 'alert' : 'status'}>
        {notice.text}
      </p>
    )}
  </>
);

export interface PackageEditorHandle {
  /** Saves unsaved edits. Resolves false when there was a problem (shown in the editor). */
  save: () => Promise<boolean>;
  isDirty: () => boolean;
}

interface Props {
  pkg: EditedPackage;
  onSaved: (pkg: EditedPackage) => void;
  /** Leave edit mode (unsaved edits are thrown away first). */
  onClose: () => void;
  onDirtyChange?: (dirty: boolean) => void;
}

type Target = { type: 'question'; key: string } | { type: 'item'; activityId: number; key: string };

/**
 * Edit a draft unit package before approving it: questions (text, options and the right one,
 * model answer, rubric), game cards, and the settings. Save sends the whole thing (PATCH);
 * "Regenerate" swaps one question or card for a new one (saving pending edits first).
 */
const PackageEditor = forwardRef<PackageEditorHandle, Props>(({ pkg, onSaved, onClose, onDirtyChange }, ref) => {
  const [initial] = useState(() => buildDraft(pkg, pkg.review?.edit_warnings ?? []));
  const [draft, setDraft] = useState<Draft>(initial.draft);
  const [base, setBase] = useState<Draft>(initial.draft);
  const [warn, setWarn] = useState<Record<string, string[]>>(initial.warn);
  const [notices, setNotices] = useState<Record<string, { text: string; tone: 'ok' | 'error' }>>({});
  const [saving, setSaving] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [savedNote, setSavedNote] = useState('');
  const [focusKey, setFocusKey] = useState<string | null>(null);

  const dirty = snapshot(draft) !== snapshot(base);
  const problems = validate(draft);
  const problemCount = problems.global.length + Object.keys(problems.byKey).length;
  const live = useRef({ draft, base, dirty, problemCount, current: pkg });
  live.current = { ...live.current, draft, base, dirty, problemCount };

  // A ref, so a parent passing an inline callback doesn't re-run these effects every render.
  const dirtyCallback = useRef(onDirtyChange);
  dirtyCallback.current = onDirtyChange;
  useEffect(() => { dirtyCallback.current?.(dirty); }, [dirty]);
  useEffect(() => () => dirtyCallback.current?.(false), []);

  const adopt = (p: EditedPackage, warnings: PackageWarning[]): Draft => {
    const next = buildDraft(p, warnings);
    live.current = { ...live.current, draft: next.draft, base: next.draft, dirty: false, current: p };
    setDraft(next.draft);
    setBase(next.draft);
    setWarn(next.warn);
    onSaved(p);
    return next.draft;
  };

  /** Save pending edits; returns the saved state, or null if it didn't save. */
  const saveNow = async (): Promise<{ pkg: EditedPackage; draft: Draft } | null> => {
    const { draft: d, base: b, dirty: isDirty, problemCount: n, current } = live.current;
    if (!isDirty) return { pkg: current, draft: d };
    if (n > 0) {
      setError('Fix the items marked "Still needed" first.');
      return null;
    }
    setSaving(true);
    setError('');
    setSavedNote('');
    try {
      const res = await updateUnitPackage(current.package_id, toEdit(d, b));
      setNotices({});
      const saved = adopt(res.package, res.warnings);
      setSavedNote(res.warnings.length
        ? `Saved. ${res.warnings.length} thing${res.warnings.length === 1 ? '' : 's'} to check below.`
        : 'Saved.');
      return { pkg: res.package, draft: saved };
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setSaving(false);
    }
  };

  useImperativeHandle(ref, () => ({
    save: async () => (await saveNow()) !== null,
    isDirty: () => live.current.dirty,
  }));

  const regenerate = async (target: Target) => {
    const d = live.current.draft;
    const index = target.type === 'question'
      ? d.questions.findIndex((q) => q.key === target.key)
      : (d.activities.find((a) => a.activity_id === target.activityId)?.items.findIndex((it) => it.key === target.key) ?? -1);
    if (index < 0) return;
    setBusyKey(target.key);
    const saved = await saveNow();
    if (!saved) { setBusyKey(null); return; }
    let req: RegenerateTarget;
    let rowKey: string;
    if (target.type === 'question') {
      req = { kind: 'question', index };
      rowKey = saved.draft.questions[index]?.key ?? target.key;
    } else {
      const itemId = saved.pkg.activities.find((a) => a.activity_id === target.activityId)?.items[index]?.item_id;
      rowKey = saved.draft.activities.find((a) => a.activity_id === target.activityId)?.items[index]?.key ?? target.key;
      if (!itemId) { setBusyKey(null); return; }
      req = { kind: 'item', activity_id: target.activityId, item_id: itemId };
    }
    setBusyKey(rowKey);
    try {
      const res = await regeneratePackagePart(saved.pkg.package_id, req);
      const next = adopt(res.package, res.warnings);
      const newKeyAt = target.type === 'question'
        ? next.questions[index]?.key
        : next.activities.find((a) => a.activity_id === target.activityId)?.items[index]?.key;
      const text = res.note
        ?? (res.generated_by === 'offline' ? 'Replaced with a new no-AI suggestion (saved).' : `Replaced with a new suggestion from ${res.generated_by} (saved).`);
      if (newKeyAt) setNotices({ [newKeyAt]: { text, tone: 'ok' } });
    } catch (e) {
      setNotices({ [rowKey]: { text: e instanceof Error ? e.message : String(e), tone: 'error' } });
    } finally {
      setBusyKey(null);
    }
  };

  // ---- immutable updates
  const setQuestion = (key: string, patch: Partial<DraftQuestion>) =>
    setDraft((d) => ({ ...d, questions: d.questions.map((q) => (q.key === key ? { ...q, ...patch } : q)) }));
  const setOption = (qKey: string, oKey: string, patch: Partial<DraftOption>) =>
    setDraft((d) => ({
      ...d,
      questions: d.questions.map((q) => (q.key !== qKey ? q : {
        ...q,
        options: q.options.map((o) => (o.key === oKey ? { ...o, ...patch } : patch.correct ? { ...o, correct: false } : o)),
      })),
    }));
  const setItem = (activityId: number, key: string, patch: Partial<DraftItem>) =>
    setDraft((d) => ({
      ...d,
      activities: d.activities.map((a) => (a.activity_id !== activityId ? a : {
        ...a, items: a.items.map((it) => (it.key === key ? { ...it, ...patch } : it)),
      })),
    }));
  const setSettings = (patch: Partial<DraftSettings>) => setDraft((d) => ({ ...d, settings: { ...d.settings, ...patch } }));

  const addQuestion = (kind: 'choice' | 'explain') => {
    const key = newKey();
    const options = kind === 'choice' ? [0, 1, 2].map(() => ({ key: newKey(), text: '', correct: false })) : [];
    setDraft((d) => ({ ...d, questions: [...d.questions, { key, kind, text: '', options, answer: '', rubric: '', source: 'teacher' }] }));
    setFocusKey(key);
  };
  const addItem = (activityId: number) => {
    const key = newKey();
    setDraft((d) => ({
      ...d,
      activities: d.activities.map((a) => (a.activity_id !== activityId ? a : {
        ...a, items: [...a.items, { key, a: '', b: '', alternates: '', source: 'teacher' }],
      })),
    }));
    setFocusKey(key);
  };

  const cancel = () => {
    setDraft(base);
    setError('');
    onClose();
  };

  const s = draft.settings;
  const busy = saving || busyKey !== null;

  return (
    <div className="mt-3 space-y-5">
      <p className="text-sm text-gray-600">
        Fix anything before you approve: what you save here is exactly what students get. Changes are kept only when you save.
      </p>

      {/* Settings */}
      <section aria-labelledby={`pkg${pkg.package_id}-settings`} className="rounded-lg border border-gray-200 p-3 space-y-3">
        <h3 id={`pkg${pkg.package_id}-settings`} className="text-sm font-semibold text-gray-900">Settings</h3>
        <label className="block text-xs font-medium text-gray-700">Title students see
          <input type="text" className={input} value={s.title} maxLength={200} onChange={(e) => setSettings({ title: e.target.value })} />
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block text-xs font-medium text-gray-700">Lesson date
            <input type="date" className={input} value={s.lesson_date}
              onChange={(e) => {
                const lesson = e.target.value;
                // A due date still on its default (the evening before) moves with the lesson.
                const follow = !s.due_local || s.due_local === eveningBefore(s.lesson_date);
                setSettings({ lesson_date: lesson, ...(follow && lesson ? { due_local: eveningBefore(lesson) } : {}) });
              }} />
          </label>
          <label className="block text-xs font-medium text-gray-700">Due
            <input type="datetime-local" className={input} value={s.due_local} onChange={(e) => setSettings({ due_local: e.target.value })} />
          </label>
          <label className="block text-xs font-medium text-gray-700">Tutor
            <select className={input} value={s.tutor_mode} onChange={(e) => setSettings({ tutor_mode: e.target.value as TutorMode })}>
              <option value="hints_only">Hints only</option>
              <option value="answer_after_tries">The answer after honest tries</option>
            </select>
          </label>
          {s.tutor_mode === 'answer_after_tries' && (
            <label className="block text-xs font-medium text-gray-700">Honest tries before the tutor explains
              <input type="number" min={1} max={10} className={input} value={s.reveal_after}
                onChange={(e) => setSettings({ reveal_after: Math.min(10, Math.max(1, Math.round(Number(e.target.value) || 1))) })} />
            </label>
          )}
          <label className="block text-xs font-medium text-gray-700">Check-in unlocks at (% of cards mastered)
            <input type="number" min={5} max={100} step={5} className={input} value={s.threshold}
              onChange={(e) => setSettings({ threshold: Math.min(100, Math.max(5, Math.round(Number(e.target.value) || 80))) })} />
          </label>
        </div>
      </section>

      {/* Games */}
      <section aria-labelledby={`pkg${pkg.package_id}-games`}>
        <h3 id={`pkg${pkg.package_id}-games`} className="text-sm font-semibold text-gray-900">Practice games</h3>
        <div className="mt-2 space-y-3">
          {draft.activities.map((a) => {
            const [fa, fb] = ITEM_FIELDS[a.kind];
            const noun = ITEM_NOUN[a.kind] ?? 'Card';
            return (
              <div key={a.key} className="rounded-lg border border-gray-200 p-3">
                <p className="text-sm font-medium text-gray-900">
                  {GAME_LABEL[a.kind] ?? a.kind} <span className="font-normal text-gray-500">· {a.items.length} card{a.items.length === 1 ? '' : 's'}</span>
                </p>
                <Notes warnings={warn[a.key]} />
                <ol className="mt-2 space-y-2">
                  {a.items.map((it, i) => {
                    const label = `${GAME_LABEL[a.kind] ?? a.kind} ${noun.toLowerCase()} ${i + 1}`;
                    return (
                      <li key={it.key} className="rounded-lg bg-gray-50 border border-gray-100 p-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-medium text-gray-500">{noun} {i + 1}</span>
                          <div className="flex gap-1.5">
                            <button type="button" className={smallBtn} disabled={busy}
                              aria-label={`Regenerate ${label}`} onClick={() => regenerate({ type: 'item', activityId: a.activity_id, key: it.key })}>
                              {busyKey === it.key ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> : <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />}
                              <span className="hidden sm:inline">Regenerate</span>
                            </button>
                            <button type="button" className={smallBtn} disabled={busy} aria-label={`Delete ${label}`}
                              onClick={() => setDraft((d) => ({ ...d, activities: d.activities.map((x) => (x.activity_id !== a.activity_id ? x : { ...x, items: x.items.filter((y) => y.key !== it.key) })) }))}>
                              <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                              <span className="hidden sm:inline">Delete</span>
                            </button>
                          </div>
                        </div>
                        <div className="mt-1 grid grid-cols-1 sm:grid-cols-2 gap-2">
                          <label className="block text-xs text-gray-600">{FIELD_LABEL[fa]}{a.kind === 'fill_in' ? ' (____ marks the blank)' : ''}
                            {a.kind === 'fill_in' ? (
                              <textarea rows={2} className={input} value={it.a} autoFocus={focusKey === it.key}
                                aria-label={`${label}: ${FIELD_LABEL[fa]}`}
                                onChange={(e) => setItem(a.activity_id, it.key, { a: e.target.value })} />
                            ) : (
                              <input type="text" className={input} value={it.a} autoFocus={focusKey === it.key}
                                aria-label={`${label}: ${FIELD_LABEL[fa]}`}
                                onChange={(e) => setItem(a.activity_id, it.key, { a: e.target.value })} />
                            )}
                          </label>
                          <label className="block text-xs text-gray-600">{FIELD_LABEL[fb]}
                            {a.kind === 'fill_in' ? (
                              <input type="text" className={input} value={it.b} aria-label={`${label}: ${FIELD_LABEL[fb]}`}
                                onChange={(e) => setItem(a.activity_id, it.key, { b: e.target.value })} />
                            ) : (
                              <textarea rows={2} className={input} value={it.b} aria-label={`${label}: ${FIELD_LABEL[fb]}`}
                                onChange={(e) => setItem(a.activity_id, it.key, { b: e.target.value })} />
                            )}
                          </label>
                          {a.kind === 'fill_in' && (
                            <label className="block text-xs text-gray-600 sm:col-span-2">Also accept (comma-separated)
                              <input type="text" className={input} value={it.alternates} aria-label={`${label}: also accept`}
                                onChange={(e) => setItem(a.activity_id, it.key, { alternates: e.target.value })} />
                            </label>
                          )}
                        </div>
                        <Notes needs={problems.byKey[it.key]} warnings={warn[it.key]} notice={notices[it.key]} />
                      </li>
                    );
                  })}
                </ol>
                <button type="button" className={`${smallBtn} mt-2`} disabled={busy} onClick={() => addItem(a.activity_id)}>
                  <Plus className="w-3.5 h-3.5" aria-hidden="true" /> Add {noun.toLowerCase()}
                  <span className="sr-only"> to {GAME_LABEL[a.kind] ?? a.kind}</span>
                </button>
              </div>
            );
          })}
        </div>
      </section>

      {/* Questions */}
      <section aria-labelledby={`pkg${pkg.package_id}-questions`}>
        <h3 id={`pkg${pkg.package_id}-questions`} className="text-sm font-semibold text-gray-900">Check-in questions ({draft.questions.length})</h3>
        <ol className="mt-2 space-y-3">
          {draft.questions.map((q, i) => {
            const n = i + 1;
            return (
              <li key={q.key} className="rounded-lg border border-gray-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-gray-900">
                    {n}.
                    <span className="ml-2 text-xs font-normal rounded-full bg-gray-100 px-2 py-0.5 text-gray-600">
                      {q.kind === 'choice' ? 'Multiple choice' : 'Explain why'}
                    </span>
                  </span>
                  <div className="flex gap-1.5">
                    <button type="button" className={smallBtn} disabled={busy} aria-label={`Regenerate question ${n}`}
                      onClick={() => regenerate({ type: 'question', key: q.key })}>
                      {busyKey === q.key ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> : <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />}
                      <span className="hidden sm:inline">Regenerate this one</span>
                    </button>
                    <button type="button" className={smallBtn} disabled={busy || draft.questions.length <= 1} aria-label={`Delete question ${n}`}
                      title={draft.questions.length <= 1 ? 'A check-in needs at least one question' : undefined}
                      onClick={() => setDraft((d) => ({ ...d, questions: d.questions.filter((x) => x.key !== q.key) }))}>
                      <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                      <span className="hidden sm:inline">Delete</span>
                    </button>
                  </div>
                </div>
                <label className="mt-2 block text-xs text-gray-600">Question {n}
                  <textarea rows={2} className={input} value={q.text} autoFocus={focusKey === q.key}
                    onChange={(e) => setQuestion(q.key, { text: e.target.value })} />
                </label>
                {q.kind === 'choice' ? (
                  <fieldset className="mt-2">
                    <legend className="text-xs text-gray-600">Answer options (pick the right one)</legend>
                    <ul className="mt-1 space-y-1.5">
                      {q.options.map((o, j) => (
                        <li key={o.key} className={`flex items-center gap-2 rounded-md px-1.5 py-1 ${o.correct ? 'bg-emerald-50' : ''}`}>
                          <input type="radio" name={`right-${q.key}`} checked={o.correct} className="h-4 w-4 shrink-0 accent-emerald-600"
                            aria-label={`Option ${j + 1} is the right answer to question ${n}`}
                            onChange={() => setOption(q.key, o.key, { correct: true })} />
                          <input type="text" className="block w-full min-w-0 rounded-lg border border-gray-300 px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-gray-400"
                            value={o.text} aria-label={`Question ${n}, option ${j + 1}`}
                            onChange={(e) => setOption(q.key, o.key, { text: e.target.value })} />
                          {o.correct && <Check className="w-4 h-4 shrink-0 text-emerald-700" aria-hidden="true" />}
                          <button type="button" className="shrink-0 rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-40"
                            disabled={q.options.length <= 2} aria-label={`Remove option ${j + 1} from question ${n}`}
                            onClick={() => setQuestion(q.key, { options: q.options.filter((x) => x.key !== o.key) })}>
                            <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                          </button>
                        </li>
                      ))}
                    </ul>
                    {q.options.length < MAX_OPTIONS && (
                      <button type="button" className={`${smallBtn} mt-1.5`}
                        onClick={() => setQuestion(q.key, { options: [...q.options, { key: newKey(), text: '', correct: false }] })}>
                        <Plus className="w-3.5 h-3.5" aria-hidden="true" /> Add option<span className="sr-only"> to question {n}</span>
                      </button>
                    )}
                  </fieldset>
                ) : (
                  <div className="mt-2 grid grid-cols-1 gap-2">
                    <label className="block text-xs text-gray-600">Model answer (only you and the tutor's judge see it)
                      <textarea rows={2} className={input} value={q.answer} onChange={(e) => setQuestion(q.key, { answer: e.target.value })} />
                    </label>
                    <label className="block text-xs text-gray-600">A good answer mentions
                      <textarea rows={2} className={input} value={q.rubric} onChange={(e) => setQuestion(q.key, { rubric: e.target.value })} />
                    </label>
                  </div>
                )}
                <Notes needs={problems.byKey[q.key]} warnings={warn[q.key]} notice={notices[q.key]} />
              </li>
            );
          })}
        </ol>
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" className={smallBtn} disabled={busy} onClick={() => addQuestion('choice')}>
            <Plus className="w-3.5 h-3.5" aria-hidden="true" /> Add multiple choice
          </button>
          <button type="button" className={smallBtn} disabled={busy} onClick={() => addQuestion('explain')}>
            <Plus className="w-3.5 h-3.5" aria-hidden="true" /> Add "explain why"
          </button>
        </div>
      </section>

      {/* Save bar */}
      <div className="sticky bottom-0 z-10 -mx-1 rounded-xl border border-gray-200 bg-white/95 px-3 py-2.5 shadow-sm backdrop-blur">
        {problems.global.length > 0 && (
          <ul className="mb-2 list-disc pl-5 text-xs text-red-700">{problems.global.map((p) => <li key={p}>{p}</li>)}</ul>
        )}
        {error && <p role="alert" className="mb-2 text-sm text-red-700">{error}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-auto text-xs text-gray-600" role="status" aria-live="polite">
            {saving ? 'Saving…' : dirty ? 'Unsaved changes' : savedNote || 'No unsaved changes'}
          </span>
          <button type="button" onClick={() => { void saveNow(); }} disabled={!dirty || busy || problemCount > 0}
            className="inline-flex items-center gap-1.5 rounded-full bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-50">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <Save className="w-4 h-4" aria-hidden="true" />}
            Save changes
          </button>
          <button type="button" onClick={cancel} disabled={busy}
            className="rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            {dirty ? 'Cancel' : 'Done editing'}
          </button>
        </div>
      </div>
    </div>
  );
});

PackageEditor.displayName = 'PackageEditor';

export default PackageEditor;
