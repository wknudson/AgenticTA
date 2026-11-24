/**
 * The "Unit check-ins" rows on the Assignments list: class progress (done / in progress / not
 * started), a Live / Due today / Due tomorrow / Closed chip, and drafts still waiting for their
 * publish approval. Rows come from the Express assignments list; the agents service adds the
 * counts, status and drafts (GET /agents/misconceptions/checkins?overview=true). If that service
 * is down the rows still show, just without progress.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Hourglass } from 'lucide-react';
import type { Assignment } from '../types';
import { BookOpen } from './Icons';
import { formatDay, formatDue, isoDay } from './checkin/format';
import {
  getCheckinOverview,
  type CheckinCounts,
  type CheckinDraft,
  type CheckinOverviewRow,
  type CheckinStatus,
  type ClassCheckinOverview,
} from '../services/classOverviewApi';

interface CheckinRowListProps {
  classId: number;
  /** The class's check-ins (mode 'checkin') from the assignments list. */
  checkins: Assignment[];
  onOpen: (a: Assignment) => void;
  onOpenApprovals: () => void;
  /** Briefing / copy link / delete buttons for one row. */
  renderActions: (a: Assignment) => React.ReactNode;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Same buckets as the server, for when the agents service isn't reachable. */
function localStatus(dueIso: string | null | undefined, now = Date.now()): CheckinStatus {
  const t = dueIso ? Date.parse(dueIso) : NaN;
  if (Number.isNaN(t)) return 'live';
  if (now > t) return 'closed';
  return t - now <= DAY_MS ? 'due_soon' : 'live';
}

function statusChip(status: CheckinStatus, dueIso: string | null | undefined): { label: string; cls: string } {
  if (status === 'closed') return { label: 'Closed', cls: 'bg-gray-100 text-gray-600 border-gray-200' };
  if (status === 'due_soon') {
    const due = dueIso ? new Date(dueIso) : null;
    const today = isoDay(new Date());
    const tomorrow = isoDay(new Date(Date.now() + DAY_MS));
    const day = due && !Number.isNaN(due.getTime()) ? isoDay(due) : '';
    const label = day === today ? 'Due today' : day === tomorrow ? 'Due tomorrow' : 'Due soon';
    return { label, cls: 'bg-amber-50 text-amber-800 border-amber-200' };
  }
  return { label: 'Live', cls: 'bg-emerald-50 text-emerald-800 border-emerald-200' };
}

/** The day used for ordering: the lesson date, else the due date's day. */
const sortDay = (lesson: string | null | undefined, due: string | null | undefined) =>
  (lesson || (due ? due.slice(0, 10) : '') || '').slice(0, 10);

const ProgressBar: React.FC<{ counts: CheckinCounts }> = ({ counts }) => {
  const { total, complete, not_started: notStarted } = counts;
  const inProgress = counts.practicing + counts.checkin;
  if (!total) return <p className="text-xs text-gray-400 mt-2">No students in this class yet</p>;
  const width = (n: number) => `${(100 * n) / total}%`;
  const label = `${complete} of ${total} done, ${inProgress} in progress, ${notStarted} not started`;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
      <div
        role="img"
        aria-label={label}
        title={`${complete} done · ${counts.checkin} in the check-in · ${counts.practicing} practicing · ${notStarted} not started`}
        className="flex h-2 w-full max-w-[16rem] overflow-hidden rounded-full bg-gray-200"
      >
        <span className="h-full bg-emerald-500" style={{ width: width(complete) }} />
        <span className="h-full bg-sky-400" style={{ width: width(inProgress) }} />
      </div>
      <span className="text-xs text-gray-600 whitespace-nowrap tabular-nums" aria-hidden="true">
        <span className="font-semibold text-gray-900">{complete}/{total} done</span>
        {inProgress > 0 && <> · {inProgress} in progress</>}
      </span>
    </div>
  );
};

const CheckinRowList: React.FC<CheckinRowListProps> = ({ classId, checkins, onOpen, onOpenApprovals, renderActions }) => {
  const [overview, setOverview] = useState<ClassCheckinOverview | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const idsKey = checkins.map((a) => a.id).join(',');

  useEffect(() => { setOverview(null); setUnavailable(false); }, [classId]);

  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      getCheckinOverview(classId, controller.signal)
        .then((o) => { setOverview(o); setUnavailable(false); })
        .catch(() => { if (!controller.signal.aborted) setUnavailable(true); });
    load();
    // Students work between visits: refresh when the teacher comes back to the tab.
    window.addEventListener('focus', load);
    return () => {
      controller.abort();
      window.removeEventListener('focus', load);
    };
  }, [classId, idsKey]);

  const rows = useMemo(() => {
    const byId = new Map<string, CheckinOverviewRow>((overview?.checkins ?? []).map((c) => [String(c.assignment_id), c]));
    const now = Date.now();
    const items = checkins.map((a) => {
      const info = byId.get(a.id);
      const due = info?.due_date ?? a.dueDateRaw ?? null;
      return {
        a,
        counts: info?.counts ?? null,
        status: info?.status ?? localStatus(due, now),
        due,
        day: sortDay(info?.lesson_date ?? a.lessonDate, due),
      };
    });
    // Open check-ins first, soonest lesson first; then closed ones, most recent first.
    items.sort((x, y) => {
      const xc = x.status === 'closed', yc = y.status === 'closed';
      if (xc !== yc) return xc ? 1 : -1;
      if (x.day !== y.day) {
        if (!x.day) return 1;
        if (!y.day) return -1;
        return xc ? y.day.localeCompare(x.day) : x.day.localeCompare(y.day);
      }
      return Number(x.a.id) - Number(y.a.id);
    });
    return items;
  }, [checkins, overview]);

  // Same-name check-ins get "#n" in the order they were created.
  const copyNumber = useMemo(() => {
    const byTitle = new Map<string, Assignment[]>();
    for (const a of checkins) {
      const key = a.title.trim().toLowerCase();
      byTitle.set(key, [...(byTitle.get(key) ?? []), a]);
    }
    const out = new Map<string, { n: number; of: number }>();
    for (const list of byTitle.values()) {
      if (list.length < 2) continue;
      [...list].sort((x, y) => Number(x.id) - Number(y.id)).forEach((a, i) => out.set(a.id, { n: i + 1, of: list.length }));
    }
    return out;
  }, [checkins]);

  const drafts: CheckinDraft[] = overview?.drafts ?? [];

  if (checkins.length === 0 && drafts.length === 0) {
    return <p className="text-gray-400 text-sm italic px-1">No unit check-ins yet.</p>;
  }

  return (
    <div className="space-y-2">
      {unavailable && (
        <p className="text-xs text-gray-500 px-1">Class progress isn't available right now (the agents service didn't answer).</p>
      )}

      {drafts.map((d) => (
        <button
          key={`draft-${d.package_id}`}
          type="button"
          onClick={onOpenApprovals}
          className="w-full text-left bg-white border border-dashed border-amber-300 rounded-2xl px-4 sm:px-5 py-4 shadow-sm hover:shadow-md transition-all flex flex-col gap-2 sm:flex-row sm:items-center focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ba3638]"
        >
          <span className="flex items-start gap-3 flex-1 min-w-0">
            <span className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 bg-amber-50 text-amber-700">
              <Hourglass className="w-4 h-4" aria-hidden="true" />
            </span>
            <span className="block min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-semibold text-black break-words">{d.title}</span>
                <span className="text-xs font-medium rounded-full border px-2 py-0.5 bg-amber-50 text-amber-800 border-amber-200">
                  Waiting for approval
                </span>
              </span>
              <span className="flex flex-wrap gap-1.5 mt-1">
                <span className="text-xs rounded-full bg-gray-100 text-gray-700 px-2 py-0.5 break-words">{d.unit}</span>
                {d.lesson_date && (
                  <span className="text-xs rounded-full bg-[#ba3638]/10 text-[#ba3638] px-2 py-0.5">Lesson {formatDay(d.lesson_date)}</span>
                )}
              </span>
            </span>
          </span>
          <span className="self-end sm:self-auto text-sm font-medium text-[#ba3638] whitespace-nowrap">Review in Approvals →</span>
        </button>
      ))}

      {rows.map(({ a, counts, status, due }) => {
        const chip = statusChip(status, due);
        const copy = copyNumber.get(a.id);
        return (
          <div
            key={a.id}
            className="bg-white border border-gray-100 rounded-2xl px-4 sm:px-5 py-4 shadow-sm hover:shadow-md transition-all group flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3"
          >
            <button
              type="button"
              onClick={() => onOpen(a)}
              className="flex items-start gap-3 flex-1 min-w-0 text-left rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ba3638]"
            >
              <span className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 transition-all bg-[#ba3638]/10 text-[#ba3638] group-hover:bg-[#ba3638] group-hover:text-white">
                <BookOpen className="w-4 h-4" />
              </span>
              <span className="block min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="font-semibold text-black break-words transition-colors group-hover:text-[#ba3638]">{a.title}</span>
                  {copy && (
                    <span className="text-xs text-gray-500" title={`Created ${copy.n} of ${copy.of} with this name`}>
                      #{copy.n}
                    </span>
                  )}
                  <span className={`text-xs font-medium rounded-full border px-2 py-0.5 whitespace-nowrap ${chip.cls}`}>{chip.label}</span>
                </span>
                {(a.unit || a.lessonDate || due) && (
                  <span className="flex flex-wrap items-center gap-1.5 mt-1">
                    {a.unit && <span className="text-xs rounded-full bg-gray-100 text-gray-700 px-2 py-0.5 break-words">{a.unit}</span>}
                    {a.lessonDate && (
                      <span className="text-xs rounded-full bg-[#ba3638]/10 text-[#ba3638] px-2 py-0.5">Lesson {formatDay(a.lessonDate)}</span>
                    )}
                    {due && <span className="text-xs text-gray-500">Due {formatDue(due)}</span>}
                  </span>
                )}
                {counts && <ProgressBar counts={counts} />}
              </span>
            </button>
            {/* Under the title on phones, so the title keeps the full width. */}
            <div className="flex items-center justify-end gap-1 border-t border-gray-100 pt-2 sm:border-0 sm:pt-0 sm:shrink-0">
              {renderActions(a)}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default CheckinRowList;
