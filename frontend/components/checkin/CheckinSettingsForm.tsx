import React, { useEffect, useMemo, useState } from 'react';
import { CalendarCheck, CheckCircle2, Info, Loader2, X } from 'lucide-react';
import type { TutorMode } from '../../services/agentsApi';
import {
  getCheckinSettings,
  updateCheckinSettings,
  type CheckinSettings,
  type CheckinSettingsPatch,
  type CheckinSettingsSaved,
} from '../../services/checkinSettingsApi';
import { eveningBefore, formatDay, formatDue, isoDay } from './format';
import LessonDayPicker from './LessonDayPicker';

interface Props {
  classId: number;
  assignmentId: number;
  onClose: () => void;
  /** Called after a successful save (the parent refreshes what it shows). */
  onSaved?: (result: CheckinSettingsSaved) => void;
}

const field = 'mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-400';
const MIN_PCT = 50;
const MAX_TRIES = 10;

/** ISO instant -> the teacher's local datetime-local value ("YYYY-MM-DDTHH:mm"). */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${isoDay(d)}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** datetime-local value -> ISO instant (UTC), or '' if invalid. */
function toInstant(local: string): string {
  if (!local) return '';
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? '' : d.toISOString();
}

interface FormState {
  title: string;
  lessonDate: string;
  due: string; // datetime-local, the teacher's time
  dueTouched: boolean; // false = follows the lesson (evening before)
  tutorMode: TutorMode;
  revealAfter: number;
  thresholdPct: number;
}

function formFrom(s: CheckinSettings): FormState {
  const due = toLocalInput(s.due_date);
  const lessonDate = s.lesson_date ?? '';
  return {
    title: s.title,
    lessonDate,
    due,
    dueTouched: !lessonDate || due !== eveningBefore(lessonDate),
    tutorMode: s.tutor_mode,
    revealAfter: s.tutor_reveal_after,
    thresholdPct: Math.round(s.mastery_threshold * 100),
  };
}

/**
 * Settings for a published unit check-in: title, lesson day, due date, tutor mode and the
 * practice threshold that unlocks the check-in. Saves only what changed; the tutor agent moves
 * the calendar entry with the due date when the scheduler's rules allow it and says why if not.
 */
const CheckinSettingsForm: React.FC<Props> = ({ classId, assignmentId, onClose, onSaved }) => {
  const [settings, setSettings] = useState<CheckinSettings | null>(null);
  const [loadError, setLoadError] = useState('');
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState<CheckinSettingsSaved | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoadError('');
    getCheckinSettings(assignmentId, controller.signal)
      .then(({ settings: s }) => {
        if (controller.signal.aborted) return;
        setSettings(s);
        setForm(formFrom(s));
      })
      .catch((e) => { if (!controller.signal.aborted) setLoadError(e instanceof Error ? e.message : String(e)); });
    return () => controller.abort();
  }, [assignmentId, reload]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, saving]);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  // The due date follows the lesson (evening before) until the teacher changes it.
  const setLesson = (day: string) => setForm((f) => (f ? {
    ...f, lessonDate: day, due: f.dueTouched ? f.due : eveningBefore(day),
  } : f));

  const dueIso = form ? toInstant(form.due) : '';
  const errors = useMemo(() => {
    const out: Partial<Record<'title' | 'lesson' | 'due' | 'threshold' | 'tries', string>> = {};
    if (!form) return out;
    if (!form.title.trim()) out.title = 'Give the check-in a title.';
    if (!form.lessonDate) out.lesson = 'Pick the lesson day.';
    if (!form.due) out.due = 'Set a due date.';
    else if (!dueIso) out.due = 'That due date is not valid.';
    else if (form.lessonDate && form.due.slice(0, 10) > form.lessonDate) {
      out.due = 'The due date must be on or before the lesson, so students finish before class.';
    }
    if (form.tutorMode === 'answer_after_tries' && !(form.revealAfter >= 1 && form.revealAfter <= MAX_TRIES)) {
      out.tries = `Use 1 to ${MAX_TRIES} tries.`;
    }
    const pctChanged = settings && form.thresholdPct !== Math.round(settings.mastery_threshold * 100);
    if (pctChanged && !(form.thresholdPct >= MIN_PCT && form.thresholdPct <= 100)) {
      out.threshold = `Use ${MIN_PCT}% to 100%.`;
    }
    return out;
  }, [form, dueIso, settings]);

  const patch = useMemo<CheckinSettingsPatch>(() => {
    if (!form || !settings) return {};
    const p: CheckinSettingsPatch = {};
    const title = form.title.trim().replace(/\s+/g, ' ');
    if (title !== settings.title) p.title = title;
    const lessonChanged = form.lessonDate !== (settings.lesson_date ?? '');
    if (lessonChanged) p.lesson_date = form.lessonDate;
    if (form.due !== toLocalInput(settings.due_date)) {
      p.due_date = dueIso;
      p.due_day = form.due.slice(0, 10);
    } else if (lessonChanged && form.due) {
      p.due_day = form.due.slice(0, 10); // so the server compares the lesson with the teacher's day
    }
    if (form.tutorMode !== settings.tutor_mode) p.tutor_mode = form.tutorMode;
    if (form.tutorMode === 'answer_after_tries' && form.revealAfter !== settings.tutor_reveal_after) {
      p.tutor_reveal_after = form.revealAfter;
    }
    if (form.thresholdPct !== Math.round(settings.mastery_threshold * 100)) p.mastery_threshold = form.thresholdPct / 100;
    return p;
  }, [form, settings, dueIso]);

  // Only real changes count (a due_day sent to check the lesson date isn't one by itself).
  const dirty = Object.keys(patch).some((k) => k !== 'due_day');
  const hasErrors = Object.keys(errors).length > 0;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!dirty || hasErrors || saving) return;
    setSaving(true);
    setSaveError('');
    try {
      const result = await updateCheckinSettings(assignmentId, patch);
      setSettings(result.settings);
      setForm(formFrom(result.settings));
      setSaved(result);
      onSaved?.(result);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const close = () => { if (!saving) onClose(); };

  return (
    <div className="fixed inset-0 z-50 flex items-start sm:items-center justify-center bg-black/40 p-4 overflow-y-auto" onClick={close}>
      <div role="dialog" aria-modal="true" aria-labelledby="checkin-settings-title"
        className="w-full max-w-xl bg-white rounded-2xl shadow-xl border border-gray-200 my-auto"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 px-6 pt-5">
          <div className="min-w-0">
            <h3 id="checkin-settings-title" className="text-xl font-bold text-black">Check-in settings</h3>
            {settings?.unit && <p className="text-sm text-gray-600 truncate">{settings.unit}</p>}
          </div>
          <button type="button" onClick={close} aria-label="Close" className="p-1.5 rounded-lg text-gray-500 hover:bg-gray-100">
            <X className="w-5 h-5" aria-hidden="true" />
          </button>
        </div>

        {loadError ? (
          <div className="px-6 py-5 space-y-3">
            <p role="alert" className="text-sm text-red-700 rounded-lg bg-red-50 border border-red-200 p-3">
              Couldn't load the settings: {loadError}
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm">Close</button>
              <button type="button" onClick={() => setReload((n) => n + 1)} className="px-4 py-2 rounded-lg bg-gray-900 text-white text-sm">Try again</button>
            </div>
          </div>
        ) : !form || !settings ? (
          <p className="px-6 py-8 text-sm text-gray-500 inline-flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Loading settings…
          </p>
        ) : saved ? (
          <div className="px-6 py-5 space-y-4">
            <p className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
              <CheckCircle2 className="w-5 h-5" aria-hidden="true" />
              {saved.changed.length ? 'Saved.' : 'Nothing changed.'}
            </p>
            {saved.notes.filter((n) => n !== 'Nothing changed.').length > 0 && (
              <ul className="space-y-2" aria-live="polite">
                {saved.notes.filter((n) => n !== 'Nothing changed.').map((n) => (
                  <li key={n} className={`flex gap-2 text-sm rounded-lg border px-3 py-2 ${
                    n === saved.calendar_note && !/^Calendar: (moved|added)/.test(n)
                      ? 'bg-amber-50 border-amber-200 text-amber-900' : 'bg-gray-50 border-gray-200 text-gray-800'}`}>
                    {n === saved.calendar_note
                      ? <CalendarCheck className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
                      : <Info className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />}
                    <span>{n}</span>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setSaved(null)} className="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm">Keep editing</button>
              <button type="button" onClick={onClose} className="px-4 py-2 rounded-lg bg-gray-900 text-white text-sm">Done</button>
            </div>
          </div>
        ) : (
          <form onSubmit={save} className="px-6 pb-5 pt-3 space-y-5" noValidate>
            <label className="block text-sm font-medium text-gray-700">Title students see
              <input type="text" className={field} value={form.title} maxLength={200} autoFocus
                aria-invalid={!!errors.title} onChange={(e) => set('title', e.target.value)} />
              {errors.title && <span className="mt-1 block text-xs text-red-700">{errors.title}</span>}
            </label>

            <div>
              <LessonDayPicker classId={classId} value={form.lessonDate || null} onChange={setLesson} label="Lesson day" />
              {errors.lesson && <p className="mt-1 text-xs text-red-700">{errors.lesson}</p>}
            </div>

            <label className="block text-sm font-medium text-gray-700">Due
              <input type="datetime-local" className={field} value={form.due} aria-invalid={!!errors.due}
                onChange={(e) => setForm((f) => (f ? { ...f, due: e.target.value, dueTouched: true } : f))} />
              <span className="mt-1 block text-xs text-gray-500">
                {form.dueTouched && form.lessonDate ? (
                  <button type="button" className="underline"
                    onClick={() => setForm((f) => (f ? { ...f, dueTouched: false, due: eveningBefore(f.lessonDate) } : f))}>
                    Reset to the evening before the lesson
                  </button>
                ) : 'Follows the lesson: the evening before.'}
                {' '}
                {settings.calendar_event
                  ? `On the class calendar: ${formatDay(settings.calendar_event.date)}${settings.calendar_event.status === 'proposed' ? ' (waiting for approval)' : ''}.`
                  : 'Not on the class calendar yet.'}
              </span>
              {errors.due && <span className="mt-1 block text-xs text-red-700">{errors.due}</span>}
            </label>

            <fieldset>
              <legend className="text-sm font-medium text-gray-700">When a student misses a question, the tutor gives…</legend>
              <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
                <label className={`rounded-xl border p-3 cursor-pointer ${form.tutorMode === 'hints_only' ? 'border-gray-900 ring-1 ring-gray-900' : 'border-gray-200 hover:border-gray-400'}`}>
                  <span className="flex items-center gap-2 text-sm font-medium text-gray-900">
                    <input type="radio" name="settings_tutor_mode" checked={form.tutorMode === 'hints_only'}
                      onChange={() => set('tutorMode', 'hints_only')} />
                    Hints only
                  </span>
                  <span className="mt-1 block text-xs text-gray-600">Questions and hints, never the answer.</span>
                </label>
                <label className={`rounded-xl border p-3 cursor-pointer ${form.tutorMode === 'answer_after_tries' ? 'border-gray-900 ring-1 ring-gray-900' : 'border-gray-200 hover:border-gray-400'}`}>
                  <span className="flex items-center gap-2 text-sm font-medium text-gray-900">
                    <input type="radio" name="settings_tutor_mode" checked={form.tutorMode === 'answer_after_tries'}
                      onChange={() => set('tutorMode', 'answer_after_tries')} />
                    The answer after honest tries
                  </span>
                  <span className="mt-1 flex items-center gap-2 text-xs text-gray-600">
                    After
                    <input type="number" min={1} max={MAX_TRIES} value={Number.isFinite(form.revealAfter) ? form.revealAfter : ''}
                      aria-label="Honest tries before the tutor explains" aria-invalid={!!errors.tries}
                      disabled={form.tutorMode !== 'answer_after_tries'}
                      onChange={(e) => set('revealAfter', e.target.value === '' ? NaN : Math.round(Number(e.target.value)))}
                      className="w-14 rounded border border-gray-300 px-2 py-0.5 text-sm disabled:bg-gray-100" />
                    tries, then the student explains it back.
                  </span>
                  {errors.tries && <span className="mt-1 block text-xs text-red-700">{errors.tries}</span>}
                </label>
              </div>
            </fieldset>

            <div>
              <label htmlFor="settings-threshold" className="block text-sm font-medium text-gray-700">
                Check-in unlocks at this share of practice cards mastered
              </label>
              <div className="mt-2 flex items-center gap-3">
                <input id="settings-threshold" type="range" min={MIN_PCT} max={100} step={5}
                  value={Math.min(100, Math.max(MIN_PCT, form.thresholdPct || MIN_PCT))}
                  onChange={(e) => set('thresholdPct', Number(e.target.value))}
                  className="flex-1 accent-gray-900" />
                <span className="flex items-center gap-1 text-sm">
                  <input type="number" min={MIN_PCT} max={100} value={Number.isFinite(form.thresholdPct) ? form.thresholdPct : ''}
                    aria-label="Unlock threshold in percent" aria-invalid={!!errors.threshold}
                    onChange={(e) => set('thresholdPct', e.target.value === '' ? NaN : Math.round(Number(e.target.value)))}
                    className="w-16 rounded border border-gray-300 px-2 py-1 text-sm" />%
                </span>
              </div>
              {errors.threshold && <p className="mt-1 text-xs text-red-700">{errors.threshold}</p>}
              <p className="mt-1 text-xs text-gray-500">
                {settings.unlocked_students > 0
                  ? `${settings.unlocked_students} student${settings.unlocked_students === 1 ? ' has' : 's have'} already unlocked it and keep${settings.unlocked_students === 1 ? 's' : ''} it whatever you choose.`
                  : 'No student has unlocked it yet.'}
              </p>
            </div>

            {form.lessonDate && dueIso && !errors.due && (
              <p className="text-sm text-gray-700">
                Students finish by <strong>{formatDue(dueIso)}</strong> for the lesson on{' '}
                <strong>{formatDay(form.lessonDate)}</strong>.
                {new Date(dueIso).getTime() < Date.now() && (
                  <span className="text-amber-800"> That's in the past: students won't be able to change their answers.</span>
                )}
              </p>
            )}
            {saveError && <p role="alert" className="text-sm text-red-700 rounded-lg bg-red-50 border border-red-200 p-3">{saveError}</p>}

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={close} disabled={saving}
                className="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-sm disabled:opacity-50">Cancel</button>
              <button type="submit" disabled={saving || !dirty || hasErrors}
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gray-900 text-white text-sm disabled:opacity-50">
                {saving && <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />}
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};

export default CheckinSettingsForm;
