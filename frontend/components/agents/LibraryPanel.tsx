import React, { useCallback, useEffect, useState } from 'react';
import { agentsFetch } from '../../services/agentsApi';
import AgentPanelShell from './AgentPanelShell';
import type { AgentPanelProps } from './registry';

/**
 * Library (filing pipeline, Phase 1).  Owner: Will.
 * TODO(Will): drag-and-drop zone, folder view grouped by unit/type, "Needs review" queue
 * with label editing, and showing search scores once vector search is in.
 */
interface LibraryFile {
  file_id: number;
  original_name: string;
  title: string | null;
  doc_type: string | null;
  unit: string | null;
  status: string;
  version: number;
}
interface Hit {
  file_id: number;
  file_title: string;
  text: string;
  score: number;
}

const LibraryPanel: React.FC<AgentPanelProps> = ({ classId }) => {
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(() => {
    agentsFetch<{ files: LibraryFile[] }>(`/filing/files?class_id=${classId}`).then((r) => setFiles(r.files)).catch(() => {});
  }, [classId]);
  useEffect(load, [load]);

  const upload = async (list: FileList | null) => {
    if (!list?.length) return;
    const form = new FormData();
    form.append('class_id', String(classId));
    Array.from(list).forEach((f) => form.append('files', f));
    setUploading(true);
    try {
      await agentsFetch('/filing/upload', { method: 'POST', body: form });
      load();
    } finally {
      setUploading(false);
    }
  };

  const search = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    const r = await agentsFetch<{ results: Hit[] }>(`/filing/search?class_id=${classId}&q=${encodeURIComponent(query)}`);
    setHits(r.results);
  };

  return (
    <AgentPanelShell agent="filing" classId={classId} onRunComplete={load}>
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
        <label className="block border-2 border-dashed border-gray-300 rounded-xl p-6 text-center text-sm text-gray-600 cursor-pointer hover:bg-gray-50">
          {uploading ? 'Filing…' : 'Drop files here or click to choose (PDF, DOCX, PPTX, TXT; images coming)'}
          <input type="file" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
        </label>
        <form onSubmit={search} className="flex gap-2">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search your materials…"
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm" />
          <button type="submit" className="px-4 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">Search</button>
        </form>
        {hits && (
          <ul className="space-y-2">
            {hits.length === 0 && <li className="text-sm text-gray-600">No matches.</li>}
            {hits.map((h, i) => (
              <li key={i} className="text-sm border border-gray-200 rounded-lg p-2">
                <span className="font-medium">{h.file_title}</span> <span className="text-gray-500">({h.score.toFixed(2)})</span>
                <p className="text-gray-600 line-clamp-2">{h.text}</p>
              </li>
            ))}
          </ul>
        )}
        <table className="w-full text-sm">
          <thead className="text-left text-gray-500">
            <tr><th className="py-1">File</th><th>Type</th><th>Unit</th><th>Status</th><th>v</th></tr>
          </thead>
          <tbody>
            {files.map((f) => (
              <tr key={f.file_id} className="border-t border-gray-100">
                <td className="py-1">{f.title || f.original_name}</td>
                <td>{f.doc_type}</td>
                <td>{f.unit ?? '—'}</td>
                <td className={f.status === 'needs_review' ? 'text-amber-700' : ''}>{f.status}</td>
                <td>{f.version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AgentPanelShell>
  );
};

export default LibraryPanel;
