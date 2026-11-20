import React, { useRef, useState } from 'react';
import { IngestResult, uploadOne } from './libraryApi';

interface Row {
  name: string;
  state: 'waiting' | 'filing' | 'done' | 'error';
  result?: IngestResult;
  error?: string;
}

/**
 * The "one bucket" drop zone.  Files are sent one at a time so each row can show its
 * own progress; reading a scan with the vision model can take several seconds.
 */
const UploadZone: React.FC<{ classId: number; onFiled: () => void }> = ({ classId, onFiled }) => {
  const [rows, setRows] = useState<Row[]>([]);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const busy = rows.some((r) => r.state === 'waiting' || r.state === 'filing');

  const run = async (files: File[]) => {
    if (!files.length) return;
    const start = rows.length;
    setRows((r) => [...r, ...files.map((f) => ({ name: f.name, state: 'waiting' as const }))]);
    for (let i = 0; i < files.length; i++) {
      const idx = start + i;
      setRows((r) => r.map((row, j) => (j === idx ? { ...row, state: 'filing' } : row)));
      try {
        const result = await uploadOne(classId, files[i]);
        setRows((r) => r.map((row, j) => (j === idx ? { ...row, state: 'done', result } : row)));
      } catch (e) {
        const error = e instanceof Error ? e.message : String(e);
        setRows((r) => r.map((row, j) => (j === idx ? { ...row, state: 'error', error } : row)));
      }
      onFiled();
    }
  };

  const outcome = (row: Row) => {
    if (row.state === 'waiting') return <span className="text-gray-500">waiting</span>;
    if (row.state === 'filing') return <span className="text-blue-700">filing…</span>;
    if (row.state === 'error') return <span className="text-red-700">failed: {row.error}</span>;
    const r = row.result!;
    if (r.duplicate) return <span className="text-gray-600">already in your library</span>;
    if (r.ai_pending) return <span className="text-blue-700">filed; AI double-checking</span>;
    if (r.status === 'needs_review') return <span className="text-amber-700">needs review: {r.review_reason}</span>;
    return <span className="text-green-700">filed</span>;
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          run(Array.from(e.dataTransfer.files));
        }}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors ${
          dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:bg-gray-50'
        }`}
      >
        <p className="font-medium text-gray-800">Drop anything here</p>
        <p className="text-sm text-gray-600 mt-1">
          Syllabi, slides, worksheets, quizzes, PDFs, Word, PowerPoint, photos of whiteboards, scans. It gets sorted for you.
        </p>
        <input
          ref={input}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            run(Array.from(e.target.files ?? []));
            e.target.value = '';
          }}
        />
      </div>
      {rows.length > 0 && (
        <div className="mt-3">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>{busy ? 'Filing…' : 'Done'}</span>
            {!busy && (
              <button type="button" className="underline" onClick={() => setRows([])}>
                clear
              </button>
            )}
          </div>
          <ul className="text-sm divide-y divide-gray-100 border border-gray-200 rounded-lg max-h-56 overflow-y-auto">
            {rows.map((row, i) => (
              <li key={i} className="px-3 py-1.5 flex justify-between gap-3">
                <span className="truncate">{row.name}</span>
                <span className="shrink-0 text-right">{outcome(row)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default UploadZone;
