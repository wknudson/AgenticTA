/** Typed calls to the filing pipeline (agents/app/agents/filing/router.py).  Owner: Will. */
import { API_BASE } from '../../../services/api';
import { agentsFetch } from '../../../services/agentsApi';

export interface DateMention {
  date: string;
  label: string;
}

export interface LibraryFile {
  file_id: number;
  original_name: string;
  title: string | null;
  doc_type: string | null;
  unit: string | null;
  summary: string | null;
  dates: DateMention[];
  status: 'filed' | 'needs_review' | 'draft' | 'archived';
  version: number;
  created_at: string | null;
  label_confidence: number | null;
  label_source: 'llm' | 'llm-fallback' | 'heuristic' | 'teacher' | null;
  review_reason: string | null;
  extract_method: 'text' | 'vision' | 'none' | null;
  mime_type: string | null;
}

export interface FileDetail extends LibraryFile {
  text_preview: string;
  text_chars: number;
}

export interface UnitSummary {
  unit: string | null;
  total: number;
  by_type: Record<string, number>;
}

export interface SearchHit {
  chunk_id: number;
  file_id: number;
  file_title: string;
  doc_type: string | null;
  unit: string | null;
  page: number | null;
  text: string;
  score: number;
  match: 'keyword' | 'semantic' | 'both';
}

export type SearchMode = 'hybrid' | 'keyword' | 'semantic';

/** Upload result row (library_files row + pipeline info). */
export interface IngestResult {
  file_id: number;
  original_name: string;
  status: LibraryFile['status'];
  review_reason: string | null;
  duplicate: boolean;
  chunk_count: number;
}

export const listFiles = (classId: number, status?: string) =>
  agentsFetch<{ files: LibraryFile[] }>(`/filing/files?class_id=${classId}${status ? `&status=${status}` : ''}`);

export const listUnits = (classId: number) =>
  agentsFetch<{ units: UnitSummary[]; doc_types: string[] }>(`/filing/units?class_id=${classId}`);

export const getFile = (fileId: number) => agentsFetch<FileDetail>(`/filing/files/${fileId}`);

export const updateLabels = (fileId: number, changes: Partial<Pick<LibraryFile, 'title' | 'doc_type' | 'unit' | 'summary' | 'dates'>>) =>
  agentsFetch<LibraryFile>(`/filing/files/${fileId}`, { method: 'PATCH', body: JSON.stringify(changes) });

export const archiveFile = (fileId: number) => agentsFetch<LibraryFile>(`/filing/files/${fileId}/archive`, { method: 'POST' });

export const reprocessFile = (fileId: number) =>
  agentsFetch<LibraryFile>(`/filing/files/${fileId}/reprocess`, { method: 'POST' });

export const reprocessReviewQueue = (classId: number) =>
  agentsFetch<{ checked: number; still_need_review: number }>(`/filing/reprocess?class_id=${classId}&which=needs_review`, {
    method: 'POST',
  });

export const downloadUrl = (fileId: number) => `${API_BASE}/agents/filing/files/${fileId}/download`;

export const searchLibrary = (classId: number, q: string, mode: SearchMode) =>
  agentsFetch<{ mode: SearchMode; results: SearchHit[] }>(
    `/filing/search?class_id=${classId}&q=${encodeURIComponent(q)}&mode=${mode}&k=8`,
  );

export async function uploadOne(classId: number, file: File): Promise<IngestResult> {
  const form = new FormData();
  form.append('class_id', String(classId));
  form.append('files', file);
  const res = await agentsFetch<{ files: IngestResult[] }>('/filing/upload', { method: 'POST', body: form });
  return res.files[0];
}

export const DOC_TYPE_LABELS: Record<string, string> = {
  syllabus: 'Syllabus',
  lecture: 'Lecture / notes',
  worksheet: 'Worksheet',
  quiz: 'Quiz',
  test: 'Test',
  lab: 'Lab',
  rubric: 'Rubric',
  reading: 'Reading',
  schedule: 'Schedule',
  other: 'Other',
};
