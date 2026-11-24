import React, { useEffect, useState } from 'react';
import { ClipboardList, Loader2 } from 'lucide-react';
import { getBriefing, getUnitPackageForAssignment, type Briefing } from '../../services/agentsApi';
import PackagePreview from './PackagePreview';

/**
 * The teacher's page for a published unit check-in (shown by AssignmentView instead of the
 * legacy question list): how far the class is, then the games and questions it was built with.
 * Legacy tools that don't fit check-ins (student preview of a graded assignment, re-saving
 * questions) are hidden by AssignmentView.
 */
const CheckinOverview: React.FC<{ classId: number; assignmentId: number; onOpenBriefing?: () => void }> = ({
  classId, assignmentId, onOpenBriefing,
}) => {
  const [packageId, setPackageId] = useState<number | null>(null);
  const [packageMissing, setPackageMissing] = useState(false);
  const [counts, setCounts] = useState<Briefing['counts'] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setPackageId(null); setPackageMissing(false); setCounts(null);
    getUnitPackageForAssignment(assignmentId, controller.signal)
      .then((p) => { if (!controller.signal.aborted) setPackageId(p.package_id); })
      .catch(() => { if (!controller.signal.aborted) setPackageMissing(true); });
    getBriefing(classId, assignmentId, controller.signal)
      .then((b) => { if (!controller.signal.aborted) setCounts(b.counts); })
      .catch(() => { /* progress is a nice-to-have here; the briefing tab shows errors */ });
    return () => controller.abort();
  }, [classId, assignmentId]);

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-gray-200 bg-gray-50 p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900">Class progress</p>
          {counts ? (
            <p className="text-sm text-gray-700">
              <strong>{counts.complete}</strong> of {counts.total} complete · {counts.checkin} in the check-in ·{' '}
              {counts.practicing} practicing · {counts.not_started} not started
            </p>
          ) : (
            <p className="text-sm text-gray-500 inline-flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Loading progress…
            </p>
          )}
        </div>
        {onOpenBriefing && (
          <button type="button" onClick={onOpenBriefing}
            className="inline-flex items-center gap-1.5 rounded-xl bg-gray-900 px-3 py-2 text-sm font-semibold text-white hover:bg-gray-800">
            <ClipboardList className="w-4 h-4" aria-hidden="true" /> Open the briefing
          </button>
        )}
      </div>
      <p className="text-xs text-gray-500">
        Students see the games first, then these questions one at a time with the tutor. To change the questions,
        draft a new check-in for the unit (editing them here would reset students' progress).
      </p>
      {packageId != null && <PackagePreview packageId={packageId} />}
      {packageMissing && (
        <p className="text-sm text-gray-600">This check-in wasn't built from a unit package, so there's no games preview.</p>
      )}
    </div>
  );
};

export default CheckinOverview;
