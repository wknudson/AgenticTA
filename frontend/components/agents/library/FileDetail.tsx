import React, { useEffect, useState } from 'react';
import {
  archiveFile,
  DateMention,
  DOC_TYPE_LABELS,
  downloadUrl,
  FileDetail as Detail,
  getFile,
  reprocessFile,
  updateLabels,
} from './libraryApi';

interface Props {
  fileId: number;
  units: string[];
  docTypes: string[];
  onClose: () => void;
  onChanged: () => void;
}

const SOURCE_TEXT: Record<string, string> = {
  auto: 'Labeled automatically from the file name and its content (no AI call)',
  llm: 'Labeled by AI',
  'llm-fallback': 'Labeled by the backup AI model',
  heuristic: 'Guessed from the file name (no AI)',
  teacher: 'Labeled by you',
};

/**
 * Side panel for one file: see what the pipeline decided, fix it, download or archive.
 * Saving marks the labels as the teacher's (and takes the file out of Needs review).
 */
const FileDetail: React.FC<Props> = ({ fileId, units, docTypes, onClose, onChanged }) => {
  const [file, setFile] = useState<Detail | null>(null);
  const [draft, setDraft] = useState({ title: '', doc_type: 'other', unit: '', summary: '' });
  const [dates, setDates] = useState<DateMention[]>([]);
  const [saving, setSaving] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = React.useCallback(() => {
    getFile(fileId)
      .then((f) => {
        setFile(f);
        setDraft({ title: f.title ?? '', doc_type: f.doc_type ?? 'other', unit: f.unit ?? '', summary: f.summary ?? '' });
        setDates(f.dates);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [fileId]);
  useEffect(load, [load]);

  const recheck = async () => {
    setRechecking(true);
    setError(null);
    try {
      await reprocessFile(fileId);
      load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRechecking(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await updateLabels(fileId, {
        title: draft.title,
        doc_type: draft.doc_type,
        unit: draft.unit.trim() || null,
        summary: draft.summary,
        dates: dates.filter((d) => d.date),
      });
      onChanged();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const archive = async () => {
    if (!window.confirm('Archive this file? It disappears from the library and search, but is kept and can be restored.')) return;
    await archiveFile(fileId);
    onChanged();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/30" onClick={onClose}>
      <aside
        className="w-full max-w-xl h-full bg-white shadow-xl overflow-y-auto p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
        aria-label="File details"
      >
        <div className="flex justify-between items-start gap-3">
          <div className="min-w-0">
            <p className="text-xs text-gray-500 truncate">{file?.original_name}</p>
            <h2 className="text-lg font-semibold text-gray-900">{file?.title ?? 'Loading…'}</h2>
          </div>
          <button type="button" onClick={onClose} className="text-gray-500 hover:text-black text-xl leading-none" aria-label="Close">
            ×
          </button>
        </div>

        {file && (
          <>
            {file.status === 'needs_review' && (
              <div className="text-sm bg-amber-50 border border-amber-200 text-amber-900 rounded-lg p-3">
                <b>Needs review:</b> {file.review_reason}. Check the labels below and save.
              </div>
            )}
            <p className="text-xs text-gray-500">
              {SOURCE_TEXT[file.label_source ?? ''] ?? 'Labeled'}
              {file.label_confidence != null && file.label_source !== 'teacher' && ` · confidence ${Math.round(file.label_confidence * 100)}%`}
              {file.extract_method === 'vision' && ' · text read from the image by AI'}
            </p>

            <label className="block text-sm">
              <span className="text-gray-700">Title</span>
              <input className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-sm">
                <span className="text-gray-700">Type</span>
                <select className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" value={draft.doc_type}
                  onChange={(e) => setDraft({ ...draft, doc_type: e.target.value })}>
                  {docTypes.map((t) => <option key={t} value={t}>{DOC_TYPE_LABELS[t] ?? t}</option>)}
                </select>
              </label>
              <label className="block text-sm">
                <span className="text-gray-700">Unit</span>
                <input className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" list="library-units" value={draft.unit}
                  placeholder="None (whole course)" onChange={(e) => setDraft({ ...draft, unit: e.target.value })} />
                <datalist id="library-units">{units.map((u) => <option key={u} value={u} />)}</datalist>
              </label>
            </div>
            <label className="block text-sm">
              <span className="text-gray-700">Summary</span>
              <textarea className="mt-1 w-full border border-gray-300 rounded-lg px-3 py-2" rows={2} value={draft.summary}
                onChange={(e) => setDraft({ ...draft, summary: e.target.value })} />
            </label>

            <div className="text-sm">
              <div className="flex justify-between items-center">
                <span className="text-gray-700">Dates found (the Scheduler uses these)</span>
                <button type="button" className="text-blue-700 text-xs" onClick={() => setDates([...dates, { date: '', label: '' }])}>
                  + add
                </button>
              </div>
              {dates.length === 0 && <p className="text-gray-500 text-xs mt-1">None</p>}
              {dates.map((d, i) => (
                <div key={i} className="flex gap-2 mt-1">
                  <input type="date" className="border border-gray-300 rounded-lg px-2 py-1" value={d.date}
                    onChange={(e) => setDates(dates.map((x, j) => (j === i ? { ...x, date: e.target.value } : x)))} />
                  <input className="flex-1 border border-gray-300 rounded-lg px-2 py-1" value={d.label} placeholder="What happens"
                    onChange={(e) => setDates(dates.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
                  <button type="button" className="text-gray-400 hover:text-red-600" aria-label="Remove date"
                    onClick={() => setDates(dates.filter((_, j) => j !== i))}>×</button>
                </div>
              ))}
            </div>

            {error && <p className="text-sm text-red-700">{error}</p>}
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={saving} onClick={save}
                className="px-4 py-2 text-sm rounded-lg bg-black text-white hover:bg-gray-800 disabled:opacity-50">
                {file.status === 'needs_review' ? 'Save & file it' : 'Save'}
              </button>
              {file.label_source !== 'teacher' && (
                <button type="button" disabled={rechecking} onClick={recheck}
                  title="Read and label this file again with AI (e.g. after the AI limit resets)"
                  className="px-4 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">
                  {rechecking ? 'Re-checking…' : 'Re-check with AI'}
                </button>
              )}
              <a href={downloadUrl(fileId)} className="px-4 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">
                Download original
              </a>
              <button type="button" onClick={archive} className="px-4 py-2 text-sm rounded-lg border border-red-200 text-red-700 hover:bg-red-50 ml-auto">
                Archive
              </button>
            </div>

            <details className="text-sm" open={file.extract_method === 'vision'}>
              <summary className="cursor-pointer text-gray-700">
                Text the pipeline read ({file.text_chars.toLocaleString()} characters)
              </summary>
              <pre className="mt-2 whitespace-pre-wrap text-xs bg-gray-50 border border-gray-200 rounded-lg p-3 max-h-80 overflow-y-auto">
                {file.text_preview || '(no readable text)'}
              </pre>
            </details>
          </>
        )}
        {!file && error && <p className="text-sm text-red-700">{error}</p>}
      </aside>
    </div>
  );
};

export default FileDetail;
