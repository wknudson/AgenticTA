import React, { useEffect, useMemo, useState } from 'react';
import LessonDayPicker from './LessonDayPicker';
import { AlertTriangle, ArrowLeft, FolderOpen, Loader2, Sparkles, Wand2 } from 'lucide-react';
import {
  createUnitPackage,
  getAgentsHealth,
  listCheckins,
  listLibraryUnits,
  type CheckinSummary,
  type LibraryUnit,
  type TutorMode,
  type UnitPackageCreated,
} from '../../services/agentsApi';
import { eveningBefore, formatDay, formatDue, isoDay } from './format';
import UnitCheckinReview from './UnitCheckinReview';

interface Props {
  classId: number;
  onCancel: () => void;
  onOpenApprovals: () => void;
  /** Preselect this unit (e.g. "Make a check-in" from a Library unit). Ignored if it has no filed files. */
  initialUnit?: string;
  /** After approving in place: open the published check-in. Without it, the success screen says where to find it. */
  onViewCheckin?: (assignmentId: number) => void;
}

const field = 'mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-400';
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, Number.isFinite(n) ? Math.round(n) : lo));

/**
 * "New unit check-in": pick a Library unit and a lesson date, set the tutor and mastery rules,
 * and the games agent drafts the practice games + check-in questions. The draft opens right here
 * (UnitCheckinReview) to fix, approve or reject; it also waits in Approvals. Nothing reaches
 * students until the teacher approves it.
 */
const UnitCheckinEditor: React.FC<Props> = ({ classId, onCancel, onOpenApprovals, initialUnit, onViewCheckin }) => {
  const [units, setUnits] = useState<LibraryUnit[] | null>(null);
  const [unitsError, setUnitsError] = useState('');
  const [aiReady, setAiReady] = useState<boolean | null>(null);
  const [checkins, setCheckins] = useState<CheckinSummary[]>([]);

  const [unit, setUnit] = useState(initialUnit ?? '');
  const [lessonDate, setLessonDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() + 2);
    return isoDay(d);
  });
  const [dueDate, setDueDate] = useState('');
  const [dueTouched, setDueTouched] = useState(false);
  const [title, setTitle] = useState('');
  const [titleTouched, setTitleTouched] = useState(false);
  const [tutorMode, setTutorMode] = useState<TutorMode>('hints_only');
  const [revealAfter, setRevealAfter] = useState(2);
  const [threshold, setThreshold] = useState(80);
  const [mcCount, setMcCount] = useState(4);
  const [explainCount, setExplainCount] = useState(2);
  const [useAi, setUseAi] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [created, setCreated] = useState<UnitPackageCreated | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setUnits(null);
    setUnitsError('');
    listLibraryUnits(classId, controller.signal)
      .then((r) => {
        if (controller.signal.aborted) return;
        const filed = r.units.filter((u) => u.unit);
        setUnits(filed);
        // Keep the preselected unit only if the Library has it; else the first unit.
        setUnit((current) => (filed.some((u) => u.unit === current) ? current : filed[0]?.unit || ''));
      })
      .catch((e) => { if (!controller.signal.aborted) setUnitsError(e instanceof Error ? e.message : String(e)); });
    listCheckins(classId, controller.signal)
      .then((r) => { if (!controller.signal.aborted) setCheckins(r.checkins); })
      .catch(() => { /* the duplicate warning is a nice-to-have */ });
    getAgentsHealth()
      .then((h) => {
        if (controller.signal.aborted) return;
        const games = h.agents.find((a) => a.name === 'games');
        const ready = !!games?.ready;
        setAiReady(ready);
        setUseAi(ready);
      })
      .catch(() => { if (!controller.signal.aborted) setAiReady(false); });
    return () => controller.abort();
  }, [classId]);

  // A preselected unit that arrives (or changes) after the units loaded.
  useEffect(() => {
    if (initialUnit && units?.some((u) => u.unit === initialUnit)) setUnit(initialUnit);
  }, [initialUnit, units]);

  // The due date follows the lesson date (evening before) until the teacher changes it.
  useEffect(() => {
    if (!dueTouched && lessonDate) setDueDate(eveningBefore(lessonDate));
  }, [lessonDate, dueTouched]);

  useEffect(() => {
    if (!titleTouched) setTitle(unit ? `${unit} practice + check-in` : '');
  }, [unit, titleTouched]);

  const today = isoDay(new Date());
  const total = mcCount + explainCount;
  const dueIso = useMemo(() => {
    if (!dueDate) return '';
    const d = new Date(dueDate);
    return Number.isNaN(d.getTime()) ? '' : d.toISOString();
  }, [dueDate]);
  const problems = [
    !unit && 'Pick a unit.',
    !lessonDate && 'Pick the lesson date.',
    lessonDate && lessonDate < today && 'The lesson date is in the past.',
    dueDate && !dueIso && 'The due date is not a valid date.',
    dueIso && lessonDate && dueDate.slice(0, 10) > lessonDate && 'The due date should be on or before the lesson.',
    total < 1 && 'Ask at least one check-in question.',
  ].filter(Boolean) as string[];

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (problems.length || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const res = await createUnitPackage({
        class_id: classId,
        unit,
        lesson_date: lessonDate,
        ...(dueIso ? { due_date: dueIso, due_day: dueDate.slice(0, 10) } : {}),
        ...(title.trim() ? { title: title.trim() } : {}),
        tutor_mode: tutorMode,
        tutor_reveal_after: revealAfter,
        mastery_threshold: threshold / 100,
        mc_count: mcCount,
        explain_count: explainCount,
        offline: !useAi,
      });
      setCreated(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (created) {
    return (
      <UnitCheckinReview
        classId={classId}
        unit={unit}
        created={created}
        onDone={onCancel}
        onOpenApprovals={onOpenApprovals}
        onViewCheckin={onViewCheckin}
        onDraftAgain={() => { setCreated(null); setError(''); }}
      />
    );
  }

  // Not blocking: two check-ins for the same unit and lesson is usually a mistake, but not always.
  const duplicate = checkins.find((c) => c.unit === unit && (c.lesson_date ?? '').slice(0, 10) === lessonDate);

  return (
    <form onSubmit={submit} className="max-w-2xl space-y-6 animate-fadeIn">
      <div>
        <button type="button" onClick={onCancel} className="inline-flex items-center gap-1 text-sm text-gray-600 hover:text-black">
          <ArrowLeft className="w-4 h-4" aria-hidden="true" /> Assignments
        </button>
        <h2 className="text-3xl font-bold text-black mt-2">New unit check-in</h2>
        <p className="text-sm text-gray-600 mt-1">
          Students practice with games at home, then answer a short check-in with the tutor. Full credit for working
          through every question; you get a briefing before class.
        </p>
      </div>

      {/* Unit + dates */}
      <section className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
        <h3 className="font-semibold text-gray-900">Unit and dates</h3>
        <label className="block text-sm font-medium text-gray-700">Unit from the Library
          {units === null && !unitsError ? (
            <p className="mt-1 text-sm text-gray-500 inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Loading units…</p>
          ) : unitsError ? (
            <p className="mt-1 text-sm text-red-700" role="alert">Couldn't load units: {unitsError}</p>
          ) : units && units.length === 0 ? (
            <p className="mt-1 text-sm text-gray-600 rounded-lg bg-gray-50 border border-gray-200 p-3 flex gap-2">
              <FolderOpen className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
              No units yet. File your materials under a unit in the Library tab, then come back.
            </p>
          ) : (
            <select className={field} value={unit} onChange={(e) => setUnit(e.target.value)} required>
              {units?.map((u) => (
                <option key={u.unit!} value={u.unit!}>{u.unit} ({u.total} file{u.total === 1 ? '' : 's'})</option>
              ))}
            </select>
          )}
        </label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="block text-sm font-medium text-gray-700">
            <LessonDayPicker classId={classId} value={lessonDate || null} onChange={setLessonDate} label="Lesson date" moveOffDaysOff />
            <span className="mt-1 block text-xs font-normal text-gray-500">
              The class this check-in prepares for. Days off and weekends come from the class calendar.
            </span>
          </div>
          <label className="block text-sm font-medium text-gray-700">Due
            <input type="datetime-local" className={field} value={dueDate}
              onChange={(e) => { setDueTouched(true); setDueDate(e.target.value); }} />
            <span className="mt-1 block text-xs text-gray-500">
              {dueTouched ? (
                <button type="button" className="underline" onClick={() => setDueTouched(false)}>Reset to the evening before</button>
              ) : 'Defaults to the evening before the lesson.'}
            </span>
          </label>
        </div>
        <div aria-live="polite">
          {duplicate && (
            <p className="text-sm text-amber-900 rounded-lg bg-amber-50 border border-amber-200 p-3 flex gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
              <span>
                There's already a check-in for <strong>{unit}</strong> before the {formatDay(lessonDate)} lesson:
                {' '}&ldquo;{duplicate.title}&rdquo;. Drafting another one gives students two check-ins for the same class.
                You can still go ahead.
              </span>
            </p>
          )}
        </div>
        <label className="block text-sm font-medium text-gray-700">Title students see
          <input type="text" className={field} value={title} maxLength={120} placeholder="Unit practice + check-in"
            onChange={(e) => { setTitleTouched(true); setTitle(e.target.value); }} />
        </label>
      </section>

      {/* Tutor + mastery */}
      <section className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
        <h3 className="font-semibold text-gray-900">Tutor and practice</h3>
        <fieldset>
          <legend className="text-sm font-medium text-gray-700">When a student misses a question, the tutor gives…</legend>
          <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
            <label className={`rounded-xl border p-3 cursor-pointer ${tutorMode === 'hints_only' ? 'border-gray-900 ring-1 ring-gray-900' : 'border-gray-200 hover:border-gray-400'}`}>
              <span className="flex items-center gap-2 text-sm font-medium text-gray-900">
                <input type="radio" name="tutor_mode" aria-label="Hints only" checked={tutorMode === 'hints_only'} onChange={() => setTutorMode('hints_only')} />
                Hints only
              </span>
              <span className="mt-1 block text-xs text-gray-600">Questions and hints, never the answer.</span>
            </label>
            <label className={`rounded-xl border p-3 cursor-pointer ${tutorMode === 'answer_after_tries' ? 'border-gray-900 ring-1 ring-gray-900' : 'border-gray-200 hover:border-gray-400'}`}>
              <span className="flex items-center gap-2 text-sm font-medium text-gray-900">
                <input type="radio" name="tutor_mode" aria-label="The answer after honest tries" checked={tutorMode === 'answer_after_tries'} onChange={() => setTutorMode('answer_after_tries')} />
                The answer after honest tries
              </span>
              <span className="mt-1 flex items-center gap-2 text-xs text-gray-600">
                After
                <input type="number" min={1} max={5} value={revealAfter} aria-label="Honest tries before the tutor explains"
                  disabled={tutorMode !== 'answer_after_tries'}
                  onChange={(e) => setRevealAfter(clamp(Number(e.target.value), 1, 5))}
                  className="w-14 rounded border border-gray-300 px-2 py-0.5 text-sm disabled:bg-gray-100" />
                tries, then the student explains it back.
              </span>
            </label>
          </div>
        </fieldset>
        <label className="block text-sm font-medium text-gray-700">
          Check-in unlocks at <span className="font-semibold text-gray-900">{threshold}%</span> of the practice cards mastered
          <input type="range" min={50} max={100} step={5} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}
            className="mt-2 block w-full accent-gray-900" />
        </label>
        <div className="grid grid-cols-2 gap-4">
          <label className="block text-sm font-medium text-gray-700">Multiple choice
            <input type="number" min={0} max={10} value={mcCount} className={field}
              onChange={(e) => setMcCount(clamp(Number(e.target.value), 0, 10))} />
          </label>
          <label className="block text-sm font-medium text-gray-700">"Explain why"
            <input type="number" min={0} max={5} value={explainCount} className={field}
              onChange={(e) => setExplainCount(clamp(Number(e.target.value), 0, 5))} />
          </label>
        </div>
      </section>

      {/* Generator */}
      <section className="bg-white rounded-2xl border border-gray-200 p-5 space-y-3">
        <h3 className="font-semibold text-gray-900">How to draft it</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label className={`rounded-xl border p-3 cursor-pointer ${useAi ? 'border-gray-900 ring-1 ring-gray-900' : 'border-gray-200 hover:border-gray-400'}`}>
            <span className="flex items-center gap-2 text-sm font-medium text-gray-900">
              <input type="radio" name="generator" aria-label="Use AI" checked={useAi} onChange={() => setUseAi(true)} />
              <Sparkles className="w-4 h-4" aria-hidden="true" /> Use AI
            </span>
            <span className="mt-1 block text-xs text-gray-600">
              Writes and reviews the cards and questions from the unit's files. Needs an API key
              {aiReady === false && <span className="text-amber-700"> (none found for the games agent)</span>}.
            </span>
          </label>
          <label className={`rounded-xl border p-3 cursor-pointer ${!useAi ? 'border-gray-900 ring-1 ring-gray-900' : 'border-gray-200 hover:border-gray-400'}`}>
            <span className="flex items-center gap-2 text-sm font-medium text-gray-900">
              <input type="radio" name="generator" aria-label="No-AI draft" checked={!useAi} onChange={() => setUseAi(false)} />
              <Wand2 className="w-4 h-4" aria-hidden="true" /> No-AI draft
            </span>
            <span className="mt-1 block text-xs text-gray-600">Builds a simpler draft straight from the unit's text. Free, works offline; review it closely.</span>
          </label>
        </div>
      </section>

      {lessonDate && (
        <p className="text-sm text-gray-700">
          Students finish by <strong>{dueDate ? formatDue(dueIso || dueDate) : 'the evening before'}</strong> for the lesson on{' '}
          <strong>{formatDay(lessonDate)}</strong>: {total} check-in question{total === 1 ? '' : 's'}, unlocked at {threshold}% practice.
        </p>
      )}
      {problems.length > 0 && <ul className="text-sm text-amber-800 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      {duplicate && problems.length === 0 && (
        <p className="text-sm text-amber-800">Heads up: this would be a second check-in for {unit} on {formatDay(lessonDate)}.</p>
      )}
      {error && <p role="alert" className="text-sm text-red-700 rounded-lg bg-red-50 border border-red-200 p-3">{error}</p>}

      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={submitting || problems.length > 0 || !units?.length}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-gray-900 text-white text-sm font-medium hover:bg-gray-800 disabled:opacity-50">
          {submitting ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <Sparkles className="w-4 h-4" aria-hidden="true" />}
          {submitting ? (useAi ? 'Drafting and reviewing… (up to a minute)' : 'Drafting…') : 'Draft the package'}
        </button>
        <button type="button" onClick={onCancel} disabled={submitting}
          className="px-5 py-2.5 rounded-full border border-gray-300 text-gray-700 text-sm font-medium hover:bg-gray-50 disabled:opacity-50">
          Cancel
        </button>
      </div>
    </form>
  );
};

export default UnitCheckinEditor;
