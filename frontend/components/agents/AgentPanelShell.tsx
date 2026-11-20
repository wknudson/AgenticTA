import React, { useEffect, useState } from 'react';
import { AgentInfo, AgentModel, getAgentsHealth, runAgentDemo, RunResult } from '../../services/agentsApi';

interface Props {
  agent: string;
  classId: number;
  /** Called after the demo/run finishes so the panel can refresh its own data. */
  onRunComplete?: () => void;
  /** Demo button text (default "Run offline demo"). */
  demoLabel?: string;
  /** Turn the demo's JSON result into one friendly line instead of showing raw JSON. */
  summarizeResult?: (result: RunResult) => string;
  demoQuery?: string;
  demoDisabled?: boolean;
  children?: React.ReactNode;
}

/**
 * Common header for every agent panel: who owns it, what kind of system it is, which
 * models it uses (and whether their keys are set), its LangSmith project, and an
 * offline demo button.  Panels put their own UI in `children`.
 */
const AgentPanelShell: React.FC<Props> = ({ agent, classId, onRunComplete, demoLabel, summarizeResult, demoQuery, demoDisabled, children }) => {
  const [info, setInfo] = useState<AgentInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);

  useEffect(() => {
    getAgentsHealth()
      .then((h) => setInfo(h.agents.find((a) => a.name === agent) ?? null))
      .catch(() => setError('The agents service is not running. Start everything with `npm run dev`.'));
  }, [agent]);

  const runDemo = async () => {
    setRunning(true);
    setResult(null);
    setError(null);
    try {
      setResult(await runAgentDemo(agent, classId, demoQuery));
      onRunComplete?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-4">
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">{info?.title ?? agent}</h1>
            <p className="text-sm text-gray-600 mt-1">
              {info?.kind ?? '…'} · {info?.pattern ?? '…'} · owner: {info?.owner ?? '…'}
            </p>
          </div>
          <button
            type="button"
            onClick={runDemo}
            disabled={running || (!!error && !info) || !!demoDisabled}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-black text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {running ? 'Running…' : demoLabel ?? 'Run offline demo'}
          </button>
        </div>
        {info && (
          <div className="flex flex-wrap gap-2 mt-3 text-xs">
            {(Object.entries(info.models) as [string, AgentModel][]).map(([role, m]) => (
              <span
                key={role}
                className={`px-2 py-1 rounded-md border ${m.key_set ? 'border-green-200 bg-green-50 text-green-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}
                title={m.key_set ? 'API key found' : 'No API key in .env; offline demo still works'}
              >
                {role}: {m.provider}/{m.model}
              </span>
            ))}
            <span className="px-2 py-1 rounded-md border border-gray-200 bg-gray-50 text-gray-700">
              LangSmith: {info.langsmith_project}
            </span>
          </div>
        )}
        {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
        {result && summarizeResult && <p className="mt-3 text-sm text-gray-800">{summarizeResult(result)}</p>}
        {result && !summarizeResult && (
          <pre className="mt-3 text-xs bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto">
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
        {result && (result as { status?: string }).status === 'waiting_for_approval' && (
          <p className="mt-2 text-sm text-gray-700">Paused for approval. Open the Approvals tab to decide.</p>
        )}
      </div>
      {children}
    </div>
  );
};

export default AgentPanelShell;
