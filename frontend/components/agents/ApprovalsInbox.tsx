import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Approval, decideApproval, listApprovals } from '../../services/agentsApi';
import PublishPreview from './calendar/PublishPreview';
import PackagePreview, { type PackagePreviewHandle } from '../checkin/PackagePreview';

/**
 * The teacher's Approvals inbox (Module 10: HITL approval dashboard).
 * Every consequential agent action lands here; nothing student-facing happens until
 * the teacher approves, edits or rejects it.  Shared by all agents.
 */
const ApprovalsInbox: React.FC<{ classId: number }> = ({ classId }) => {
  const [items, setItems] = useState<Approval[]>([]);
  const [statusFilter, setStatusFilter] = useState<'pending' | ''>('pending');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [editing, setEditing] = useState<Record<number, string>>({});
  const [lastResult, setLastResult] = useState<string | null>(null);
  // Unit packages can be edited here before approving (PackagePreview); unsaved edits are saved first.
  const packagePreviews = useRef<Record<number, PackagePreviewHandle | null>>({});
  const [unsaved, setUnsaved] = useState<Record<number, boolean>>({});

  const load = useCallback(() => {
    listApprovals(classId, statusFilter)
      .then((r) => setItems(r.approvals))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [classId, statusFilter]);

  useEffect(load, [load]);

  const decide = async (a: Approval, type: 'approve' | 'edit' | 'reject') => {
    setBusy(a.approval_id);
    setError(null);
    try {
      const preview = packagePreviews.current[a.approval_id];
      if (type === 'approve' && preview?.isDirty() && !(await preview.save())) {
        setError('The package edits weren\'t saved, so nothing was approved. Fix what the editor points out, or cancel the edits.');
        return;
      }
      let edited_args: Record<string, unknown> | undefined;
      if (type === 'edit') edited_args = JSON.parse(editing[a.approval_id] ?? JSON.stringify(a.action_args));
      const message = type === 'reject' ? window.prompt('Why? (sent back to the agent)') ?? undefined : undefined;
      const res = await decideApproval(a.approval_id, { type, edited_args, message });
      setLastResult(JSON.stringify(res.result ?? res, null, 2));
      setEditing(({ [a.approval_id]: _, ...rest }) => rest);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Approvals</h1>
        <div className="flex gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'pending' | '')}
            className="text-sm border border-gray-300 rounded-lg px-2 py-1"
          >
            <option value="pending">Pending</option>
            <option value="">All</option>
          </select>
          <button type="button" onClick={load} className="text-sm px-3 py-1 rounded-lg border border-gray-300 hover:bg-white">
            Refresh
          </button>
        </div>
      </div>
      {error && <p className="text-sm text-red-700">{error}</p>}
      {items.length === 0 && <p className="text-sm text-gray-600">Nothing is waiting for you.</p>}
      {items.map((a) => (
        <div key={a.approval_id} className="bg-white rounded-xl border border-gray-200 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <span className="text-xs uppercase tracking-wide text-gray-500">{a.agent}</span>
              <h2 className="font-medium text-gray-900">{a.description || a.action_name}</h2>
              <p className="text-xs text-gray-500">
                {a.action_name} · needs {a.required_role} · {new Date(a.created_at).toLocaleString()}
                {a.status !== 'pending' && ` · ${a.status}`}
              </p>
            </div>
            {a.status === 'pending' && (
              <div className="flex gap-2">
                {a.allowed_decisions.includes('approve') && (
                  <button type="button" disabled={busy === a.approval_id} onClick={() => decide(a, 'approve')}
                    className="px-3 py-1.5 text-sm rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">
                    {unsaved[a.approval_id] ? 'Save and approve' : 'Approve'}
                  </button>
                )}
                {a.allowed_decisions.includes('edit') && (
                  editing[a.approval_id] === undefined ? (
                    <button type="button" onClick={() => setEditing((s) => ({ ...s, [a.approval_id]: JSON.stringify(a.action_args, null, 2) }))}
                      className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">
                      Edit
                    </button>
                  ) : (
                    <button type="button" disabled={busy === a.approval_id} onClick={() => decide(a, 'edit')}
                      className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                      Save edit &amp; approve
                    </button>
                  )
                )}
                {a.allowed_decisions.includes('reject') && (
                  <button type="button" disabled={busy === a.approval_id} onClick={() => decide(a, 'reject')}
                    className="px-3 py-1.5 text-sm rounded-lg border border-red-300 text-red-700 hover:bg-red-50 disabled:opacity-50">
                    Reject
                  </button>
                )}
              </div>
            )}
          </div>
          {editing[a.approval_id] !== undefined ? (
            <textarea
              value={editing[a.approval_id]}
              onChange={(e) => setEditing((s) => ({ ...s, [a.approval_id]: e.target.value }))}
              rows={8}
              className="mt-3 w-full font-mono text-xs border border-gray-300 rounded-lg p-2"
            />
          ) : a.action_name === 'publish_calendar' && Array.isArray(a.action_args.event_ids) ? (
            <>
              <PublishPreview classId={classId} eventIds={a.action_args.event_ids as number[]} />
              <details className="mt-2 text-xs text-gray-500">
                <summary className="cursor-pointer">Raw request</summary>
                <pre className="mt-1 bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto">{JSON.stringify(a.action_args, null, 2)}</pre>
              </details>
            </>
          ) : a.action_name === 'publish_unit_package' && Number(a.action_args.package_id) > 0 ? (
            <>
              <PackagePreview
                packageId={Number(a.action_args.package_id)}
                editable={a.status === 'pending'}
                ref={(h: PackagePreviewHandle | null) => { packagePreviews.current[a.approval_id] = h; }}
                onDirtyChange={(d: boolean) => setUnsaved((s) => (s[a.approval_id] === d ? s : { ...s, [a.approval_id]: d }))}
              />
              <details className="mt-2 text-xs text-gray-500">
                <summary className="cursor-pointer">Raw request</summary>
                <pre className="mt-1 bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto">{JSON.stringify(a.action_args, null, 2)}</pre>
              </details>
            </>
          ) : (
            <pre className="mt-3 text-xs bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto">
              {JSON.stringify(a.action_args, null, 2)}
            </pre>
          )}
        </div>
      ))}
      {lastResult && (
        <details className="text-xs text-gray-700">
          <summary className="cursor-pointer">Agent response after the last decision</summary>
          <pre className="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto">{lastResult}</pre>
        </details>
      )}
    </div>
  );
};

export default ApprovalsInbox;
