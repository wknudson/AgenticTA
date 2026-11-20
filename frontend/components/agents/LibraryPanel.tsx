import React, { useCallback, useEffect, useMemo, useState } from 'react';
import AgentPanelShell from './AgentPanelShell';
import FileDetail from './library/FileDetail';
import {
  DOC_TYPE_LABELS,
  LibraryFile,
  listFiles,
  listUnits,
  reprocessReviewQueue,
  searchLibrary,
  SearchHit,
  SearchMode,
  UnitSummary,
} from './library/libraryApi';
import UploadZone from './library/UploadZone';
import type { AgentPanelProps } from './registry';

/**
 * Library (filing pipeline, Phase 1).  Owner: Will.
 * Drop zone -> auto-sorted folders by unit and type -> Needs-review queue -> search.
 */
type Tab = 'files' | 'review' | 'search';
const ALL = '__all__';
const NO_UNIT = '__none__';

const MATCH_BADGE: Record<SearchHit['match'], { text: string; cls: string }> = {
  both: { text: 'keyword + meaning', cls: 'bg-purple-50 text-purple-800 border-purple-200' },
  semantic: { text: 'meaning', cls: 'bg-blue-50 text-blue-800 border-blue-200' },
  keyword: { text: 'keyword', cls: 'bg-gray-50 text-gray-700 border-gray-200' },
};

const SOURCE_BADGE: Record<string, string> = {
  auto: 'auto', llm: 'AI', 'llm-fallback': 'AI (backup)', heuristic: 'auto', teacher: 'you',
};

function highlight(text: string, q: string): React.ReactNode {
  const terms = q.split(/\s+/).filter((t) => t.length > 2).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  if (!terms.length) return text;
  const re = new RegExp(`(${terms.join('|')})`, 'gi');
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i} className="bg-yellow-100">{part}</mark> : part));
}

const LibraryPanel: React.FC<AgentPanelProps> = ({ classId }) => {
  const [tab, setTab] = useState<Tab>('files');
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [units, setUnits] = useState<UnitSummary[]>([]);
  const [docTypes, setDocTypes] = useState<string[]>([]);
  const [unitFilter, setUnitFilter] = useState<string>(ALL);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [openFile, setOpenFile] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchMode>('hybrid');
  const [results, setResults] = useState<{ q: string; mode: SearchMode; hits: SearchHit[] } | null>(null);
  const [searching, setSearching] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const [recheckNote, setRecheckNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recheckAll = async () => {
    setRechecking(true);
    setRecheckNote(null);
    try {
      const r = await reprocessReviewQueue(classId);
      setRecheckNote(`Re-checked ${r.checked} file(s); ${r.still_need_review} still need review.`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRechecking(false);
    }
  };

  const load = useCallback(() => {
    Promise.all([listFiles(classId), listUnits(classId)])
      .then(([f, u]) => {
        setFiles(f.files);
        setUnits(u.units);
        setDocTypes(u.doc_types);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [classId]);
  useEffect(load, [load]);

  // While the batched AI queue works on some files, refresh every few seconds so their labels update.
  const anyPending = files.some((f) => f.ai_pending);
  useEffect(() => {
    if (!anyPending) return;
    const t = window.setInterval(load, 4000);
    return () => window.clearInterval(t);
  }, [anyPending, load]);

  const review = files.filter((f) => f.status === 'needs_review');
  const unitNames = units.map((u) => u.unit).filter((u): u is string => !!u);
  const shown = useMemo(
    () =>
      files.filter(
        (f) =>
          (unitFilter === ALL || (unitFilter === NO_UNIT ? !f.unit : f.unit === unitFilter)) &&
          (!typeFilter || f.doc_type === typeFilter),
      ),
    [files, unitFilter, typeFilter],
  );
  const typesInView = useMemo(() => Array.from(new Set(files.filter((f) =>
    unitFilter === ALL || (unitFilter === NO_UNIT ? !f.unit : f.unit === unitFilter)).map((f) => f.doc_type ?? 'other'))).sort(),
  [files, unitFilter]);

  const runSearch = async (e?: React.FormEvent, m: SearchMode = mode) => {
    e?.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    try {
      const r = await searchLibrary(classId, query, m);
      setResults({ q: query, mode: r.mode, hits: r.results });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  };

  const fileRow = (f: LibraryFile, showReason = false) => (
    <li key={f.file_id}>
      <button type="button" onClick={() => setOpenFile(f.file_id)}
        className="w-full text-left px-3 py-2 hover:bg-gray-50 flex items-center gap-3">
        <span className="text-xs px-2 py-0.5 rounded-md border border-gray-200 bg-gray-50 text-gray-700 shrink-0 w-28 text-center">
          {DOC_TYPE_LABELS[f.doc_type ?? 'other'] ?? f.doc_type}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm text-gray-900 truncate">{f.title || f.original_name}</span>
          <span className="block text-xs text-gray-500 truncate">
            {showReason ? f.review_reason : `${f.original_name}${f.unit ? ` · ${f.unit}` : ''}${f.dates.length ? ` · ${f.dates.length} date(s)` : ''}`}
          </span>
        </span>
        {f.ai_pending && !showReason && <span className="text-xs text-blue-700 shrink-0">AI checking…</span>}
        {f.status === 'needs_review' && !f.ai_pending && !showReason && <span className="text-xs text-amber-700 shrink-0">review</span>}
        <span className="text-xs text-gray-400 shrink-0" title="Who labeled it">{SOURCE_BADGE[f.label_source ?? ''] ?? ''}</span>
      </button>
    </li>
  );

  const tabBtn = (t: Tab, label: string) => (
    <button type="button" onClick={() => setTab(t)}
      className={`px-3 py-1.5 text-sm rounded-lg ${tab === t ? 'bg-black text-white' : 'text-gray-700 hover:bg-gray-100'}`}>
      {label}
    </button>
  );

  return (
    <AgentPanelShell
      agent="filing"
      classId={classId}
      onRunComplete={load}
      demoLabel="File the sample course"
      summarizeResult={(r) => {
        const out = r as { filed?: number; files?: Array<{ status: string; duplicate: boolean }> };
        const review = out.files?.filter((f) => !f.duplicate && f.status === 'needs_review').length ?? 0;
        return `Filed ${out.filed ?? 0} new file(s)${review ? `, ${review} need review` : ''}${
          out.files && out.filed === 0 ? ' (they were already in the library)' : ''}.`;
      }}
    >
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <UploadZone classId={classId} onFiled={load} />

        <div className="flex flex-wrap items-center gap-2 border-b border-gray-100 pb-3">
          {tabBtn('files', `Files (${files.length})`)}
          {tabBtn('review', `Needs review (${review.length})`)}
          {tabBtn('search', 'Search')}
        </div>
        {error && <p className="text-sm text-red-700">{error}</p>}

        {tab === 'files' && (
          <div className="flex flex-col md:flex-row gap-4">
            <nav className="md:w-56 shrink-0 space-y-1" aria-label="Units">
              {[{ key: ALL, label: 'All files', n: files.length },
                ...units.map((u) => ({ key: u.unit ?? NO_UNIT, label: u.unit ?? 'Whole course', n: u.total }))].map((u) => (
                <button key={u.key} type="button" onClick={() => { setUnitFilter(u.key); setTypeFilter(null); }}
                  className={`w-full text-left px-3 py-1.5 rounded-lg text-sm flex justify-between gap-2 ${
                    unitFilter === u.key ? 'bg-gray-100 font-medium' : 'hover:bg-gray-50'}`}>
                  <span className="truncate">{u.label}</span>
                  <span className="text-gray-500">{u.n}</span>
                </button>
              ))}
            </nav>
            <div className="flex-1 min-w-0">
              <div className="flex flex-wrap gap-1 mb-2">
                {typesInView.map((t) => (
                  <button key={t} type="button" onClick={() => setTypeFilter(typeFilter === t ? null : t)}
                    className={`text-xs px-2 py-1 rounded-full border ${
                      typeFilter === t ? 'bg-black text-white border-black' : 'border-gray-300 text-gray-700 hover:bg-gray-50'}`}>
                    {DOC_TYPE_LABELS[t] ?? t}
                  </button>
                ))}
              </div>
              {shown.length === 0 ? (
                <p className="text-sm text-gray-600 py-6 text-center">
                  {files.length ? 'Nothing here.' : 'No files yet. Drop some above, or click "File the sample course".'}
                </p>
              ) : (
                <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">{shown.map((f) => fileRow(f))}</ul>
              )}
            </div>
          </div>
        )}

        {tab === 'review' && (
          review.length === 0 ? (
            <p className="text-sm text-gray-600 py-6 text-center">Nothing needs your review.</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-sm text-gray-600 flex-1 min-w-[240px]">
                  These were filed, but the pipeline wasn't sure or couldn't use AI at the time. Open one to fix and save it,
                  or re-check them all with AI.
                </p>
                <button type="button" disabled={rechecking} onClick={recheckAll}
                  className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">
                  {rechecking ? 'Re-checking…' : 'Re-check all with AI'}
                </button>
              </div>
              {recheckNote && <p className="text-sm text-gray-700">{recheckNote}</p>}
              <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg">{review.map((f) => fileRow(f, true))}</ul>
            </>
          )
        )}

        {tab === 'search' && (
          <div className="space-y-3">
            <form onSubmit={runSearch} className="flex flex-wrap gap-2">
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder='Try "how do plants make food" or "Unit 2 test"'
                className="flex-1 min-w-[200px] border border-gray-300 rounded-lg px-3 py-2 text-sm" />
              <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm" role="group" aria-label="Search mode">
                {(['hybrid', 'keyword', 'semantic'] as SearchMode[]).map((m) => (
                  <button key={m} type="button" onClick={() => { setMode(m); if (results) runSearch(undefined, m); }}
                    className={`px-3 py-2 ${mode === m ? 'bg-black text-white' : 'hover:bg-gray-50'}`}>
                    {m === 'semantic' ? 'meaning' : m}
                  </button>
                ))}
              </div>
              <button type="submit" disabled={searching}
                className="px-4 py-2 text-sm rounded-lg bg-black text-white hover:bg-gray-800 disabled:opacity-50">
                {searching ? 'Searching…' : 'Search'}
              </button>
            </form>
            {results && results.mode !== mode && (
              <p className="text-xs text-amber-700">No embedding key, so this used keyword search.</p>
            )}
            {results && (
              results.hits.length === 0 ? (
                <p className="text-sm text-gray-600">
                  Nothing in this class's library matches that closely. Try other words, or check you're in the right class.
                </p>
              ) : (
                <ul className="space-y-2">
                  {results.hits.map((h) => (
                    <li key={h.chunk_id}>
                      <button type="button" onClick={() => setOpenFile(h.file_id)}
                        className="w-full text-left border border-gray-200 rounded-lg p-3 hover:bg-gray-50">
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                          <span className="font-medium text-gray-900">{h.file_title}</span>
                          {h.page != null && <span className="text-gray-500">p. {h.page}</span>}
                          {h.unit && <span className="text-gray-500">· {h.unit}</span>}
                          <span className={`ml-auto text-xs px-2 py-0.5 rounded-md border ${MATCH_BADGE[h.match].cls}`}>
                            {MATCH_BADGE[h.match].text}
                          </span>
                        </div>
                        <p className="text-sm text-gray-600 mt-1 line-clamp-3">{highlight(h.text, results.q)}</p>
                      </button>
                    </li>
                  ))}
                </ul>
              )
            )}
          </div>
        )}
      </div>

      {openFile != null && (
        <FileDetail fileId={openFile} units={unitNames} docTypes={docTypes} onClose={() => setOpenFile(null)} onChanged={load} />
      )}
    </AgentPanelShell>
  );
};

export default LibraryPanel;
