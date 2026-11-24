import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Check, Loader2, Pencil } from 'lucide-react';
import { getUnitPackage, type GameItem, type PackageActivity } from '../../services/agentsApi';
import type { EditedPackage } from '../../services/packageApi';
import { GAME_LABEL, formatDay, formatDue, tutorModeLabel } from './format';
import PackageEditor, { type PackageEditorHandle } from './PackageEditor';

const SAMPLE_CARDS = 3;

function cardParts(kind: string, item: GameItem): [string, string] {
  if (kind === 'matching') return [item.term ?? '', item.definition ?? ''];
  if (kind === 'fill_in') {
    const alts = item.alternates?.length ? ` (also: ${item.alternates.join(', ')})` : '';
    return [item.sentence ?? '', `${item.answer ?? ''}${alts}`];
  }
  return [item.front ?? item.term ?? '', item.back ?? item.definition ?? ''];
}

const CardList: React.FC<{ activity: PackageActivity; items: GameItem[] }> = ({ activity, items }) => (
  <ul className="mt-2 space-y-1.5">
    {items.map((item) => {
      const [front, back] = cardParts(activity.kind, item);
      return (
        <li key={item.item_id} className="text-sm rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 break-words">
          <span className="text-gray-900">{front}</span>
          <span className="text-gray-400" aria-hidden="true"> → </span>
          <span className="text-gray-600">{back}</span>
        </li>
      );
    })}
  </ul>
);

export interface PackagePreviewHandle {
  /** Save unsaved edits (true when there was nothing to save). False = a problem, shown in the editor. */
  save: () => Promise<boolean>;
  isDirty: () => boolean;
}

interface Props {
  packageId: number;
  /** Offer editing while the package is still a draft (Approvals, approve-in-place). */
  editable?: boolean;
  /** Open straight in edit mode (when editable and a draft). */
  startEditing?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  /** After every save / regenerate, with the stored package. */
  onPackageChange?: (pkg: EditedPackage) => void;
}

/**
 * What publish_unit_package would publish: the games (counts + sample cards), every check-in
 * question with the right answers marked, and the settings students will get. With `editable`,
 * a draft can be fixed first (PackageEditor); otherwise it's read-only (e.g. a published check-in).
 */
const PackagePreview = forwardRef<PackagePreviewHandle, Props>(({
  packageId, editable = false, startEditing = false, onDirtyChange, onPackageChange,
}, ref) => {
  const [pkg, setPkg] = useState<EditedPackage | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState(false);
  const editor = useRef<PackageEditorHandle | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setPkg(null);
    setError('');
    setEditing(false);
    getUnitPackage(packageId, controller.signal)
      .then((p) => {
        if (controller.signal.aborted) return;
        setPkg(p as EditedPackage);
        setEditing(editable && startEditing && p.status === 'draft');
      })
      .catch((e) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e)); });
    return () => controller.abort();
    // Reload only when the package changes; editable/startEditing only matter on load.
  }, [packageId]); // eslint-disable-line react-hooks/exhaustive-deps

  useImperativeHandle(ref, () => ({
    save: () => (editor.current ? editor.current.save() : Promise.resolve(true)),
    isDirty: () => editor.current?.isDirty() ?? false,
  }));

  if (error) return <p className="mt-3 text-sm text-red-700" role="alert">Couldn't load the package: {error}</p>;
  if (!pkg) {
    return (
      <p className="mt-3 text-sm text-gray-500 inline-flex items-center gap-2">
        <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Loading the package…
      </p>
    );
  }

  const canEdit = editable && pkg.status === 'draft';
  if (editing && canEdit) {
    return (
      <PackageEditor
        ref={editor}
        pkg={pkg}
        onSaved={(p) => { setPkg(p); onPackageChange?.(p); }}
        onClose={() => setEditing(false)}
        onDirtyChange={onDirtyChange}
      />
    );
  }

  const s = pkg.settings ?? {};
  const threshold = typeof s.mastery_threshold === 'number' ? Math.round(s.mastery_threshold * 100) : null;
  const settings: Array<[string, string]> = [
    ['Unit', pkg.unit],
    ['Lesson', s.lesson_date ? formatDay(String(s.lesson_date), true) : '–'],
    ['Due', s.due_date ? formatDue(String(s.due_date)) : 'Evening before the lesson'],
    ['Tutor', tutorModeLabel(s.tutor_mode, typeof s.tutor_reveal_after === 'number' ? s.tutor_reveal_after : undefined)],
    ['Unlocks at', threshold != null ? `${threshold}% of cards mastered` : '–'],
    ['Written by', pkg.generated_by?.startsWith('offline') ? 'No-AI draft' : pkg.generated_by ?? '–'],
  ];

  return (
    <div className="mt-3 space-y-4">
      {pkg.status !== 'draft' && (
        <p className="text-sm text-amber-800 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
          This package is already {pkg.status}.
        </p>
      )}
      {canEdit && (
        <button type="button" onClick={() => setEditing(true)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-800 hover:bg-gray-50">
          <Pencil className="w-4 h-4" aria-hidden="true" /> Edit before approving
        </button>
      )}
      {typeof s.title === 'string' && s.title && <p className="text-sm text-gray-700">Students will see <strong>{s.title}</strong>.</p>}
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-sm">
        {settings.map(([k, v]) => (
          <div key={k} className="flex gap-2 min-w-0">
            <dt className="w-24 shrink-0 text-gray-500">{k}</dt>
            <dd className="text-gray-900 min-w-0 break-words">{v}</dd>
          </div>
        ))}
      </dl>

      <section>
        <h3 className="text-sm font-semibold text-gray-900">Practice games</h3>
        {pkg.activities.length === 0 && <p className="text-sm text-gray-500 mt-1">No games in this package.</p>}
        <div className="mt-2 space-y-3">
          {pkg.activities.map((a) => (
            <div key={a.activity_id} className="rounded-lg border border-gray-200 p-3">
              <p className="text-sm font-medium text-gray-900">
                {GAME_LABEL[a.kind] ?? a.kind} <span className="font-normal text-gray-500">· {a.items.length} card{a.items.length === 1 ? '' : 's'}</span>
              </p>
              {a.title && <p className="text-xs text-gray-500">{a.title}</p>}
              <CardList activity={a} items={a.items.slice(0, SAMPLE_CARDS)} />
              {a.items.length > SAMPLE_CARDS && (
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs text-gray-600">Show all {a.items.length}</summary>
                  <CardList activity={a} items={a.items.slice(SAMPLE_CARDS)} />
                </details>
              )}
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-gray-900">Check-in questions ({pkg.questions.length})</h3>
        <ol className="mt-2 space-y-3">
          {pkg.questions.map((q, i) => (
            <li key={i} className="rounded-lg border border-gray-200 p-3">
              <p className="text-sm text-gray-900 break-words">
                <span className="font-semibold">{i + 1}.</span> {q.text}
                <span className="ml-2 text-xs rounded-full bg-gray-100 px-2 py-0.5 text-gray-600">
                  {q.kind === 'choice' ? 'Multiple choice' : 'Explain why'}
                </span>
              </p>
              {q.kind === 'choice' && (
                <ul className="mt-2 space-y-1">
                  {(q.options ?? []).map((o, j) => (
                    <li key={j} className={`flex items-start gap-2 text-sm rounded-md px-2 py-1 ${o.correct ? 'bg-emerald-50 text-emerald-900' : 'text-gray-700'}`}>
                      {o.correct ? <Check className="w-4 h-4 mt-0.5 shrink-0" aria-label="Correct answer" /> : <span className="w-4 shrink-0" aria-hidden="true" />}
                      <span className="break-words min-w-0">{o.text}</span>
                    </li>
                  ))}
                </ul>
              )}
              {q.kind === 'explain' && (
                <div className="mt-2 space-y-1 text-sm">
                  {q.answer && <p className="text-gray-700 break-words"><span className="text-gray-500">Model answer:</span> {q.answer}</p>}
                  {q.rubric && <p className="text-gray-700 break-words"><span className="text-gray-500">A good answer mentions:</span> {q.rubric}</p>}
                </div>
              )}
            </li>
          ))}
        </ol>
        <p className="mt-2 text-xs text-gray-500">Model answers and rubrics are only for you and the tutor's judge; students never see them.</p>
      </section>
    </div>
  );
});

PackagePreview.displayName = 'PackagePreview';

export default PackagePreview;
