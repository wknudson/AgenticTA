import React, { useCallback, useEffect, useState } from 'react';
import AgentPanelShell from './AgentPanelShell';
import { agentsFetch, RunResult } from '../../services/agentsApi';
import type { AgentPanelProps } from './registry';
import BriefingPanel from '../checkin/BriefingPanel';

type Suggestion = { explanation: string; material_update: string; reteaching_activity: string; supporting_student_count?: number };
type Insight = { insight_id: number; topic: string; evidence_count: number; examples: string[]; suggestion: Suggestion; model_used: string; status: string };
type Analysis = { chats_read: number; questions_analyzed: number; insights_found: number; insights_suppressed: number; latency_seconds: number };
type Assignment = { assignment_id: number; assignment_name: string; due_date: string | null; mode?: string; analysis_status: 'eligible' | 'upcoming' | 'no_due_date' };
type AnalysisScope = 'course' | 'assignment';
const InsightsPanel: React.FC<AgentPanelProps> = ({ classId }) => {
  const [insights, setInsights] = useState<Insight[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [scope, setScope] = useState<AnalysisScope>('course');
  const [assignmentId, setAssignmentId] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [drafted, setDrafted] = useState<string[]>([]);
  const load = useCallback(async (signal?: AbortSignal) => {
    const result = await agentsFetch<{ insights: Insight[] }>(`/misconceptions/insights?class_id=${classId}`, { signal });
    if (!signal?.aborted) setInsights(result.insights);
  }, [classId]);
  useEffect(() => {
    const controller = new AbortController();
    setInsights([]); setAssignments([]); setAssignmentId(''); setError(''); setNotice(''); setDrafted([]); setLoading(true);
    load(controller.signal).catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    agentsFetch<{ assignments: Assignment[] }>(`/misconceptions/assignments?class_id=${classId}`, { signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return;
        setAssignments(result.assignments);
        setAssignmentId(current => result.assignments.some(a => String(a.assignment_id) === current && a.analysis_status === 'eligible')
          ? current : String(result.assignments.find(a => a.analysis_status === 'eligible')?.assignment_id ?? ''));
      }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [load]);
  const refresh = () => { load().catch(e => setError(e.message)); };
  const analyze = async () => {
    if (scope === 'assignment' && !assignmentId) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const assignmentQuery = scope === 'assignment' ? `&assignment_id=${assignmentId}` : '';
      const result = await agentsFetch<Analysis>(`/misconceptions/run?class_id=${classId}${assignmentQuery}`, { method: 'POST' });
      const heldBack = result.insights_suppressed ? ` Held back ${result.insights_suppressed} pattern(s) with fewer than 3 questions or fewer than 2 students; gather more chats and analyze again.` : '';
      const scopeLabel = scope === 'course' ? 'across the course' : 'for this assignment';
      setNotice(`Analyzed ${result.questions_analyzed} of ${result.chats_read} recent chats ${scopeLabel}; found ${result.insights_found} supported recommendation(s) in ${result.latency_seconds}s.${heldBack}`);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const approveAndDraft = async (insight: Insight) => {
    setBusy(true); setError(''); setNotice('');
    try {
      // The backend sends only the approved topic and recommendation, never excerpts.
      const result = await agentsFetch<RunResult>(`/misconceptions/insights/${insight.insight_id}/draft?class_id=${classId}`, { method: 'POST' });
      setDrafted(previous => [...previous, String(insight.insight_id)]);
      setNotice(result.status === 'waiting_for_approval'
        ? 'Recommendation approved. The material draft is waiting for a second approval in Approvals.'
        : String(('output' in result ? result.output : null) ?? 'The material agent finished. Review its draft and Approvals before applying changes.'));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return (
    <>
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 pt-6"><BriefingPanel classId={classId} onInsightsChanged={refresh} /></div>
    <AgentPanelShell agent="misconceptions" classId={classId} onRunComplete={refresh}
      demoQuery={scope === 'assignment' && assignmentId ? `&assignment_id=${assignmentId}` : ''}
      demoDisabled={loading || (scope === 'assignment' && (!assignmentId || assignments.find(a => String(a.assignment_id) === assignmentId)?.analysis_status !== 'eligible'))}>
      <div className="bg-white rounded-xl border p-5 space-y-3">
        <h2 className="text-lg font-semibold">What students may be struggling with</h2>
        <p className="text-sm text-gray-600">Names, emails, and phone numbers are masked first; only aggregate timing and counts are traced. Analysis uses up to 100 recent tutor questions.</p>
        <label className="block text-sm font-medium">Analyze
          <select className="mt-1 block w-full rounded-lg border p-2" value={scope} onChange={event => setScope(event.target.value as AnalysisScope)} disabled={busy || loading}>
            <option value="course">All course chats (run manually)</option>
            <option value="assignment">One assignment (after its due date; check-ins any time)</option>
          </select>
        </label>
        {scope === 'assignment' && <>
          <label className="block text-sm font-medium">Assignment
            <select className="mt-1 block w-full rounded-lg border p-2" value={assignmentId} onChange={event => setAssignmentId(event.target.value)} disabled={busy || loading}>
              <option value="">Choose an assignment</option>
              {assignments.map(assignment => <option key={assignment.assignment_id} value={assignment.assignment_id}>
                {assignment.assignment_name} — {assignment.mode === 'checkin' ? 'check-in, open now' : assignment.analysis_status === 'eligible' ? 'due date passed' : assignment.analysis_status === 'upcoming' ? `due ${assignment.due_date ? new Date(assignment.due_date).toLocaleString() : 'date pending'}` : 'no due date'}
              </option>)}
            </select>
          </label>
          <p className="text-xs text-gray-500">Assignment-specific analysis becomes available after the selected due date. Check-ins can be analyzed before it, so the briefing is ready before class.</p>
        </>}
        <button className="bg-black text-white rounded-lg px-4 py-2 disabled:opacity-40" onClick={analyze} disabled={busy || loading || (scope === 'assignment' && (!assignmentId || assignments.find(a => String(a.assignment_id) === assignmentId)?.analysis_status !== 'eligible'))}>{busy ? 'Working…' : 'Analyze chats locally'}</button>
        <p className="text-sm text-gray-600">Approving a recommendation below sends its topic and proposed teaching changes to the materials agent. It drafts a revision for a second approval; no file is changed by the first approval.</p>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        {notice && <p role="status" className="text-green-800">{notice}</p>}
      </div>
      {!loading && insights.length === 0 && <p className="text-gray-600">No insights yet. Analyze tutor chats or run the offline demo for sample cards.</p>}
      {insights.map(insight => (
        <article key={insight.insight_id} className="bg-white rounded-xl border p-5 space-y-3">
          <div className="flex justify-between gap-3"><h3 className="font-semibold">{insight.topic}</h3><span className="text-sm text-gray-500">{insight.evidence_count} questions · {insight.suggestion.supporting_student_count ?? 'multiple'} students</span></div>
          <p className="text-sm text-gray-500">{insight.model_used.startsWith('offline:') ? 'Offline demonstration · keyword grouping, not model analysis' : `Local analysis · ${insight.model_used}`}</p>
          <p className="text-sm">{insight.suggestion.explanation}</p>
          <div className="rounded-lg bg-gray-50 p-4 space-y-2 text-sm">
            <p><strong>Suggested material update:</strong> {insight.suggestion.material_update}</p>
            {insight.suggestion.reteaching_activity && <p><strong>Reteaching idea:</strong> {insight.suggestion.reteaching_activity}</p>}
          </div>
          {insight.examples.length > 0 && <div><p className="text-sm font-medium">Anonymized examples</p><ul className="space-y-2">{insight.examples.map((example, index) => <li key={index} className="border-l-2 border-gray-300 pl-3 text-sm text-gray-600">{example}</li>)}</ul></div>}
          <p className="text-xs text-gray-500">These questions suggest a review topic; they do not establish individual student understanding.</p>
          <button disabled={busy || insight.status !== 'new' || drafted.includes(String(insight.insight_id))} className="border rounded-lg px-3 py-2 disabled:opacity-40" onClick={() => approveAndDraft(insight)}>
            {insight.status !== 'new' || drafted.includes(String(insight.insight_id)) ? 'Draft requested' : 'Approve suggestion & draft update'}
          </button>
        </article>
      ))}
    </AgentPanelShell>
    </>
  );
};
export default InsightsPanel;
