import React, { useCallback, useEffect, useState } from 'react';
import AgentPanelShell from './AgentPanelShell';
import { agentsFetch, RunResult } from '../../services/agentsApi';
import type { AgentPanelProps } from './registry';

type Suggestion = { explanation: string; material_update: string; reteaching_activity: string };
type Insight = { insight_id: number; topic: string; evidence_count: number; examples: string[]; suggestion: Suggestion; model_used: string; status: string };
type Analysis = { chats_read: number; questions_analyzed: number; insights_found: number; latency_seconds: number };
const InsightsPanel: React.FC<AgentPanelProps> = ({ classId }) => {
  const [insights, setInsights] = useState<Insight[]>([]);
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
    setInsights([]); setError(''); setNotice(''); setDrafted([]); setLoading(true);
    load(controller.signal).catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [load]);
  const refresh = () => { load().catch(e => setError(e.message)); };
  const analyze = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await agentsFetch<Analysis>(`/misconceptions/run?class_id=${classId}`, { method: 'POST' });
      setNotice(`Analyzed ${result.questions_analyzed} of ${result.chats_read} recent questions locally; found ${result.insights_found} possible misconceptions in ${result.latency_seconds}s.`);
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
    <AgentPanelShell agent="misconceptions" classId={classId} onRunComplete={refresh}>
      <div className="bg-white rounded-xl border p-5 space-y-3">
        <h2 className="text-lg font-semibold">What students may be struggling with</h2>
        <p className="text-sm text-gray-600">Analyze up to 100 recent tutor questions with local Ollama. Names, emails, and phone numbers are masked first. Only aggregate timing and counts are traced.</p>
        <button className="bg-black text-white rounded-lg px-4 py-2 disabled:opacity-40" onClick={analyze} disabled={busy || loading}>{busy ? 'Working…' : 'Analyze chats locally'}</button>
        <p className="text-sm text-gray-600">Approving a recommendation below sends its topic and proposed teaching changes to the materials agent. It drafts a revision for a second approval; no file is changed by the first approval.</p>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        {notice && <p role="status" className="text-green-800">{notice}</p>}
      </div>
      {!loading && insights.length === 0 && <p className="text-gray-600">No insights yet. Analyze tutor chats or run the offline demo for sample cards.</p>}
      {insights.map(insight => (
        <article key={insight.insight_id} className="bg-white rounded-xl border p-5 space-y-3">
          <div className="flex justify-between gap-3"><h3 className="font-semibold">{insight.topic}</h3><span className="text-sm text-gray-500">{insight.evidence_count} questions</span></div>
          <p className="text-sm text-gray-500">{insight.model_used.startsWith('offline:') ? 'Offline demonstration · keyword grouping, not model analysis' : `Local analysis · ${insight.model_used}`}</p>
          <p className="text-sm">{insight.suggestion.explanation}</p>
          <div className="rounded-lg bg-gray-50 p-4 space-y-2 text-sm">
            <p><strong>Suggested material update:</strong> {insight.suggestion.material_update}</p>
            {insight.suggestion.reteaching_activity && <p><strong>Reteaching idea:</strong> {insight.suggestion.reteaching_activity}</p>}
          </div>
          <ul className="space-y-2">{insight.examples.map((example, index) => <li key={index} className="border-l-2 border-gray-300 pl-3 text-sm text-gray-600">{example}</li>)}</ul>
          <p className="text-xs text-gray-500">These questions suggest a review topic; they do not establish individual student understanding.</p>
          <button disabled={busy || insight.status !== 'new' || drafted.includes(String(insight.insight_id))} className="border rounded-lg px-3 py-2 disabled:opacity-40" onClick={() => approveAndDraft(insight)}>
            {insight.status !== 'new' || drafted.includes(String(insight.insight_id)) ? 'Draft requested' : 'Approve suggestion & draft update'}
          </button>
        </article>
      ))}
    </AgentPanelShell>
  );
};
export default InsightsPanel;
