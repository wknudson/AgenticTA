/**
 * Client for the Python agents service.  In dev, Vite proxies /agents -> http://127.0.0.1:8000.
 * Agent owners add their own calls at the bottom of this file (or in their panel file).
 */
import { API_BASE } from './api';

export interface AgentModel {
  provider: string;
  model: string;
  key_set: boolean;
}

export interface AgentInfo {
  name: string;
  title: string;
  owner: string | null;
  kind: string | null;
  pattern: string | null;
  models: Record<string, AgentModel>;
  ready: boolean;
  langsmith_project: string;
}

export interface AgentsHealth {
  status: string;
  db_path: string;
  keys: Record<string, boolean>;
  agents: AgentInfo[];
}

export interface Approval {
  approval_id: number;
  group_id: string;
  position: number;
  agent: string;
  class_id: number | null;
  action_name: string;
  action_args: Record<string, unknown>;
  description: string | null;
  allowed_decisions: Array<'approve' | 'edit' | 'reject'>;
  required_role: 'teacher' | 'admin';
  status: 'pending' | 'approved' | 'edited' | 'rejected';
  created_at: string;
}

export type RunResult =
  | { status: 'waiting_for_approval'; thread_id: string; approval_groups: string[] }
  | { status: 'done'; thread_id: string; output: string | null }
  | Record<string, unknown>;

export async function agentsFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/agents${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init?.headers },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new Error(typeof detail === 'string' ? detail : `Agents service error ${res.status}`);
  }
  return body as T;
}

export const getAgentsHealth = () => agentsFetch<AgentsHealth>('/health');

export const runAgentDemo = (agent: string, classId: number, extraQuery = '') =>
  agentsFetch<RunResult>(`/${agent}/demo?class_id=${classId}${extraQuery}`, { method: 'POST' });

export const listApprovals = (classId: number, status: string = 'pending') =>
  agentsFetch<{ approvals: Approval[] }>(`/approvals?class_id=${classId}&status=${encodeURIComponent(status)}`);

export const decideApproval = (
  approvalId: number,
  decision: { type: 'approve' | 'edit' | 'reject'; edited_args?: Record<string, unknown>; message?: string },
) =>
  agentsFetch<{ status: string; result?: RunResult }>(`/approvals/${approvalId}/decide`, {
    method: 'POST',
    body: JSON.stringify({ ...decision, decided_by: 'teacher', role: 'teacher' }),
  });
