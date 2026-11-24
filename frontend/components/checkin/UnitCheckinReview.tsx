import React, { useRef, useState } from 'react';
import { CheckCircle2, ExternalLink, Inbox, Loader2, RotateCcw, Send, XCircle } from 'lucide-react';
import { getUnitPackage, type UnitPackageCreated } from '../../services/agentsApi';
import { decideUnitPackage, decisionOutput } from '../../services/packageApi';
import PackagePreview, { type PackagePreviewHandle } from './PackagePreview';

interface Props {
  classId: number;
  unit: string;
  created: UnitPackageCreated;
  /** "Back to assignments". */
  onDone: () => void;
  onOpenApprovals: () => void;
  /** Open the published check-in (shown as "View the check-in" when given). */
  onViewCheckin?: (assignmentId: number) => void;
  /** Back to the form after a reject, with the same settings. */
  onDraftAgain: () => void;
}

type Phase = 'review' | 'approved' | 'rejected';

const pill = 'inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium disabled:opacity-50';

/**
 * Approve in place: right after the games agent drafts a unit package, the teacher sees it here,
 * can fix it (PackagePreview in edit mode), and approves or rejects the same pending approval
 * the Approvals inbox shows (publish_unit_package for this package_id). "Review later" leaves it there.
 */
const UnitCheckinReview: React.FC<Props> = ({
  classId, unit, created, onDone, onOpenApprovals, onViewCheckin, onDraftAgain,
}) => {
  const preview = useRef<PackagePreviewHandle | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null);
  const [error, setError] = useState('');
  const [phase, setPhase] = useState<Phase>('review');
  const [confirmReject, setConfirmReject] = useState(false);
  const [reason, setReason] = useState('');
  const [output, setOutput] = useState('');
  const [assignmentId, setAssignmentId] = useState<number | null>(null);
  const [title, setTitle] = useState('');
  const packageId = created.package_id;
  const s = created.summary;

  /** After a failed decision: maybe someone already decided it in Approvals (another tab). */
  const syncStatus = async () => {
    try {
      const p = await getUnitPackage(packageId);
      if (p.status === 'published') {
        setAssignmentId(p.assignment_id);
        setTitle(typeof p.settings?.title === 'string' ? p.settings.title : '');
        setPhase('approved');
      } else if (p.status === 'rejected') {
        setPhase('rejected');
      }
    } catch { /* keep the error that's already shown */ }
  };

  const approve = async () => {
    if (busy) return;
    setBusy('approve');
    setError('');
    try {
      if (preview.current?.isDirty() && !(await preview.current.save())) {
        setError('Your edits weren\'t saved, so nothing was approved. Fix what the editor points out, or cancel the edits.');
        return;
      }
      const res = await decideUnitPackage(classId, packageId, 'approve');
      setOutput(decisionOutput(res));
      const p = await getUnitPackage(packageId).catch(() => null);
      setAssignmentId(p?.assignment_id ?? null);
      setTitle(typeof p?.settings?.title === 'string' ? p.settings.title : '');
      setPhase('approved');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await syncStatus();
    } finally {
      setBusy(null);
    }
  };

  const reject = async () => {
    if (busy) return;
    setBusy('reject');
    setError('');
    try {
      await decideUnitPackage(classId, packageId, 'reject', reason.trim() || undefined);
      setPhase('rejected');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await syncStatus();
    } finally {
      setBusy(null);
    }
  };

  if (phase === 'approved') {
    return (
      <div className="max-w-2xl animate-fadeIn">
        <div className="bg-white rounded-2xl border border-gray-200 p-6 space-y-4" role="status">
          <div className="flex items-start gap-3">
            <CheckCircle2 className="w-7 h-7 text-emerald-600 shrink-0" aria-hidden="true" />
            <div className="min-w-0">
              <h2 className="text-xl font-bold text-gray-900">Published to students</h2>
              <p className="text-sm text-gray-600 mt-1">
                {title ? <>&ldquo;{title}&rdquo; is live: </> : 'The check-in is live: '}
                students can play the {unit} games now, and the check-in unlocks when they reach the mastery bar.
              </p>
              {output && <p className="text-sm text-gray-700 mt-2 break-words">{output}</p>}
              {!onViewCheckin && (
                <p className="text-sm text-gray-600 mt-2">You'll find it in your assignments list{title ? ` as "${title}"` : ''}.</p>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {onViewCheckin && assignmentId != null && (
              <button type="button" onClick={() => onViewCheckin(assignmentId)} className={`${pill} bg-gray-900 text-white hover:bg-gray-800`}>
                <ExternalLink className="w-4 h-4" aria-hidden="true" /> View the check-in
              </button>
            )}
            <button type="button" onClick={onDone} className={`${pill} border border-gray-300 text-gray-700 hover:bg-gray-50`}>
              Back to assignments
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (phase === 'rejected') {
    return (
      <div className="max-w-2xl animate-fadeIn">
        <div className="bg-white rounded-2xl border border-gray-200 p-6 space-y-4" role="status">
          <div className="flex items-start gap-3">
            <XCircle className="w-7 h-7 text-gray-500 shrink-0" aria-hidden="true" />
            <div className="min-w-0">
              <h2 className="text-xl font-bold text-gray-900">Draft rejected</h2>
              <p className="text-sm text-gray-600 mt-1">Nothing was published. You can draft the {unit} check-in again with different settings.</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onDraftAgain} className={`${pill} bg-gray-900 text-white hover:bg-gray-800`}>
              <RotateCcw className="w-4 h-4" aria-hidden="true" /> Draft again
            </button>
            <button type="button" onClick={onDone} className={`${pill} border border-gray-300 text-gray-700 hover:bg-gray-50`}>
              Back to assignments
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-5 animate-fadeIn">
      <div>
        <h2 className="text-3xl font-bold text-black">Review and approve</h2>
        <p className="text-sm text-gray-600 mt-1">
          The {unit} package is a draft: students see nothing until you approve it. Fix anything below first;
          approving publishes the games, the check-in and a calendar entry for the due date.
        </p>
      </div>

      {s && (
        <ul className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-sm" aria-label="What the agent drafted">
          {([
            ['Flashcards', s.flashcards], ['Matching pairs', s.matching], ['Fill-in blanks', s.fill_in],
            ['Multiple choice', s.mc], ['Explain why', s.explain],
          ] as Array<[string, number]>).map(([label, n]) => (
            <li key={label} className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
              <span className="block text-lg font-semibold text-gray-900">{n}</span>
              <span className="text-gray-600">{label}</span>
            </li>
          ))}
          <li className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2">
            <span className="block text-sm font-semibold text-gray-900 truncate">{s.generated_by?.startsWith('offline') ? 'No-AI draft' : s.generated_by}</span>
            <span className="text-gray-600">Written by</span>
          </li>
        </ul>
      )}
      {s && <p className="text-xs text-gray-500">Counts are from the first draft; the preview below shows the package as it is now.</p>}

      <section className="bg-white rounded-2xl border border-gray-200 p-4 sm:p-5">
        <PackagePreview ref={preview} packageId={packageId} editable startEditing onDirtyChange={setDirty} />
      </section>

      <div className="bg-white rounded-2xl border border-gray-200 p-4 sm:p-5 space-y-3">
        {error && <p role="alert" className="text-sm text-red-700 rounded-lg bg-red-50 border border-red-200 p-3">{error}</p>}
        {confirmReject ? (
          <div className="space-y-3">
            <p className="text-sm text-gray-800">Reject this draft? Nothing is published and the draft is closed.</p>
            <label className="block text-sm font-medium text-gray-700">Why? (optional, kept with the approval)
              <input type="text" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-400" />
            </label>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={reject} disabled={busy !== null} className={`${pill} bg-red-600 text-white hover:bg-red-700`}>
                {busy === 'reject' ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <XCircle className="w-4 h-4" aria-hidden="true" />}
                Reject the draft
              </button>
              <button type="button" onClick={() => setConfirmReject(false)} disabled={busy !== null}
                className={`${pill} border border-gray-300 text-gray-700 hover:bg-gray-50`}>
                Keep it
              </button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={approve} disabled={busy !== null} className={`${pill} bg-emerald-600 text-white hover:bg-emerald-700`}>
              {busy === 'approve' ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <Send className="w-4 h-4" aria-hidden="true" />}
              {busy === 'approve' ? 'Publishing…' : dirty ? 'Save and approve' : 'Approve and publish'}
            </button>
            <button type="button" onClick={() => setConfirmReject(true)} disabled={busy !== null}
              className={`${pill} border border-red-300 text-red-700 hover:bg-red-50`}>
              <XCircle className="w-4 h-4" aria-hidden="true" /> Reject
            </button>
            <button type="button" onClick={onOpenApprovals} disabled={busy !== null}
              className={`${pill} border border-gray-300 text-gray-700 hover:bg-gray-50`}
              title={dirty ? 'Unsaved edits are not kept' : undefined}>
              <Inbox className="w-4 h-4" aria-hidden="true" /> Review later in Approvals
            </button>
          </div>
        )}
        {dirty && !confirmReject && (
          <p className="text-xs text-gray-500">You have unsaved edits: approving saves them first. Leaving for Approvals doesn't keep them.</p>
        )}
      </div>
    </div>
  );
};

export default UnitCheckinReview;
