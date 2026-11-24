import React, { useEffect, useState } from 'react';
import { BookOpen, CalendarPlus, Clock, FileText, Hourglass, Loader2 } from 'lucide-react';
import type { FeedCheckin } from '../../../services/schedulerFeedApi';
import { formatDue } from '../../checkin/format';
import { Term, dayOffReason, longDate, shortDate, todayISO } from './calendarUtils';
import {
  CHECKIN_PALETTE,
  CheckinColor,
  DayItems,
  STATUS_CHIP,
  checkinDueDay,
  dayOf,
  dueBeforeLesson,
  practiceWindow,
} from './classCalendarData';
import DayEditor from './DayEditor';

/**
 * Everything on one day of the class calendar: its check-ins (lesson, due, practice), scheduler
 * events (DayEditor), graded assignments due and check-in drafts, plus "New check-in for this
 * lesson day". Also the keyboard and phone way to move a check-in's lesson (no drag needed).
 */
interface Props {
  classId: number;
  day: string;
  term: Term | null;
  items: DayItems;
  colors: Map<number, CheckinColor>;
  /** Conflicts on this day, as sentences. */
  problems: string[];
  /** Refetch the calendar (after DayEditor changes). */
  onChanged: () => Promise<void>;
  onMoveCheckin: (checkin: FeedCheckin, lessonDay: string) => Promise<void>;
  /** A move is running: hold other moves. */
  moving: boolean;
  onOpenCheckin?: (assignmentId: number) => void;
  onOpenBriefing?: (assignmentId: number) => void;
  onOpenApprovals?: () => void;
  onStartCheckin?: (unit: string | null, lessonDate?: string) => void;
}

const smallBtn = 'px-2.5 py-1.5 rounded-lg text-xs font-medium border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-40';
const heading = 'text-xs font-semibold uppercase tracking-wide text-gray-500';

const Progress: React.FC<{ counts: FeedCheckin['counts'] }> = ({ counts }) => {
  const { total, complete } = counts;
  if (!total) return <p className="text-xs text-gray-400">No students in this class yet.</p>;
  const inProgress = counts.practicing + counts.checkin;
  const width = (n: number) => `${(100 * n) / total}%`;
  return (
    <div className="space-y-1">
      <div role="img" aria-label={`${complete} of ${total} done, ${inProgress} in progress, ${counts.not_started} not started`}
        className="flex h-2 w-full overflow-hidden rounded-full bg-gray-200">
        <span className="h-full bg-emerald-500" style={{ width: width(complete) }} />
        <span className="h-full bg-sky-400" style={{ width: width(inProgress) }} />
      </div>
      <p className="text-xs text-gray-600 tabular-nums" aria-hidden="true">
        <span className="font-semibold text-gray-900">{complete}/{total} done</span>
        {counts.checkin > 0 && <> · {counts.checkin} in the check-in</>}
        {counts.practicing > 0 && <> · {counts.practicing} practicing</>}
        {counts.not_started > 0 && <> · {counts.not_started} not started</>}
      </p>
    </div>
  );
};

/** Keyboard/phone alternative to dragging the lesson chip. */
const MoveLesson: React.FC<{ checkin: FeedCheckin; term: Term | null; moving: boolean; onMove: Props['onMoveCheckin'] }> = ({
  checkin, term, moving, onMove,
}) => {
  const current = dayOf(checkin.lesson_date) ?? '';
  const [value, setValue] = useState(current);
  useEffect(() => { setValue(current); }, [current]);
  const reason = value && value !== current ? dayOffReason(value, term) : null;
  const due = value && value !== current && !reason ? dueBeforeLesson(value, checkin.due_date) : null;
  return (
    <div className="space-y-1">
      <div className="flex items-end gap-2">
        <label className="flex-1 min-w-0 text-xs text-gray-600">Move the lesson to
          <input type="date" value={value} min={term?.term_start || undefined} max={term?.term_end || undefined}
            onChange={(e) => setValue(e.target.value)}
            className="mt-0.5 block w-full rounded-lg border border-gray-300 px-2 py-1 text-sm" />
        </label>
        <button type="button" className={smallBtn} disabled={moving || !value || value === current || !!reason}
          onClick={() => onMove(checkin, value)}>
          Move
        </button>
      </div>
      {reason && <p className="text-xs text-amber-800">{reason} Pick a school day.</p>}
      {due && <p className="text-xs text-gray-500">The due moves to {formatDue(due.due_date)} (the evening before).</p>}
    </div>
  );
};

const DayPanel: React.FC<Props> = ({
  classId, day, term, items, colors, problems, onChanged, onMoveCheckin, moving,
  onOpenCheckin, onOpenBriefing, onOpenApprovals, onStartCheckin,
}) => {
  const off = dayOffReason(day, term);
  const past = day < todayISO();
  // One card per check-in with its lesson or due on this day; practice-only check-ins listed after.
  const main: FeedCheckin[] = [];
  for (const c of [...items.lessons, ...items.dues]) if (!main.some((m) => m.assignment_id === c.assignment_id)) main.push(c);
  const practiceOnly = items.windows.filter((c) => !main.some((m) => m.assignment_id === c.assignment_id));
  const drafts = [...items.draftLessons, ...items.draftDues]
    .filter((d, i, all) => all.findIndex((x) => x.package_id === d.package_id) === i);
  const colorOf = (id: number) => colors.get(id) ?? CHECKIN_PALETTE[0];

  return (
    <div className="space-y-5">
      <div>
        <h3 className="font-semibold text-gray-900">{longDate(day)}</h3>
        {off && <p className="text-sm text-amber-800">{off.replace(`${longDate(day)} is `, 'This day is ')}</p>}
        {problems.map((p) => <p key={p} className="text-sm text-red-700">Conflict: {p}</p>)}
      </div>

      {(main.length > 0 || practiceOnly.length > 0 || drafts.length > 0) && (
        <section className="space-y-2" aria-label="Check-ins">
          <h4 className={heading}>Check-ins</h4>
          <ul className="space-y-2">
            {main.map((c) => {
              const isLesson = dayOf(c.lesson_date) === day;
              const isDue = checkinDueDay(c) === day;
              const status = STATUS_CHIP[c.status] ?? STATUS_CHIP.live;
              return (
                <li key={c.assignment_id} className="rounded-xl border border-gray-200 p-3 space-y-2">
                  <div className="flex items-start gap-2">
                    <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${colorOf(c.assignment_id).dot}`} aria-hidden="true" />
                    <p className="flex-1 min-w-0 text-sm font-medium text-gray-900 break-words">{c.title}</p>
                    <span className={`shrink-0 text-[11px] font-medium rounded-full border px-2 py-0.5 ${status.cls}`}>{status.label}</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5 text-xs">
                    {isLesson && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#ba3638]/10 text-[#ba3638] px-2 py-0.5">
                        <BookOpen className="w-3 h-3" aria-hidden="true" /> Lesson day
                      </span>
                    )}
                    {isDue && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 text-gray-700 px-2 py-0.5">
                        <Clock className="w-3 h-3" aria-hidden="true" /> Due {c.due_date ? formatDue(c.due_date) : 'today'}
                      </span>
                    )}
                    {!isLesson && c.lesson_date && <span className="text-gray-500">Lesson {shortDate(dayOf(c.lesson_date)!)}</span>}
                    {c.unit && <span className="rounded-full bg-gray-100 text-gray-700 px-2 py-0.5 break-words">{c.unit}</span>}
                  </div>
                  <Progress counts={c.counts} />
                  {(onOpenCheckin || onOpenBriefing) && (
                    <div className="flex flex-wrap gap-2">
                      {onOpenCheckin && <button type="button" className={smallBtn} onClick={() => onOpenCheckin(c.assignment_id)}>Open check-in</button>}
                      {onOpenBriefing && <button type="button" className={smallBtn} onClick={() => onOpenBriefing(c.assignment_id)}>Briefing</button>}
                    </div>
                  )}
                  {isLesson && <MoveLesson checkin={c} term={term} moving={moving} onMove={onMoveCheckin} />}
                </li>
              );
            })}
            {practiceOnly.map((c) => {
              const w = practiceWindow(c);
              return (
                <li key={c.assignment_id} className="flex items-center gap-2 text-sm">
                  <span className={`w-4 h-2 rounded-full shrink-0 ${colorOf(c.assignment_id).band.split(' ')[0]}`} aria-hidden="true" />
                  <span className="flex-1 min-w-0 text-gray-700 break-words">
                    Practice open: {c.title}
                    {w && <span className="text-gray-500"> (until {shortDate(w.end)})</span>}
                  </span>
                  {onOpenCheckin && (
                    <button type="button" className="text-xs underline text-gray-700 shrink-0" onClick={() => onOpenCheckin(c.assignment_id)}>Open</button>
                  )}
                </li>
              );
            })}
            {drafts.map((d) => (
              <li key={`draft-${d.package_id}`} className="rounded-xl border border-dashed border-gray-400 p-3 space-y-1">
                <p className="flex items-start gap-2 text-sm font-medium text-gray-900">
                  <Hourglass className="w-4 h-4 mt-0.5 shrink-0 text-amber-700" aria-hidden="true" />
                  <span className="break-words">{d.title}</span>
                </p>
                <p className="text-xs text-gray-600">
                  Draft, waiting for approval.
                  {dayOf(d.lesson_date) === day ? ' Lesson day.' : dayOf(d.due_day) === day ? ' Due this day.' : ''}
                </p>
                {onOpenApprovals && (
                  <button type="button" className="text-xs font-medium text-[#ba3638] underline" onClick={onOpenApprovals}>
                    Review in Approvals
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2" aria-label="Calendar events">
        <h4 className={heading}>Calendar events</h4>
        <DayEditor classId={classId} date={day} term={term} events={items.events} problems={problems}
          onChanged={onChanged} showHeader={false} emptyText="No quizzes, labs or other events this day." />
      </section>

      {items.assignments.length > 0 && (
        <section className="space-y-2" aria-label="Graded assignments due">
          <h4 className={heading}>Graded assignments due</h4>
          <ul className="space-y-1.5">
            {items.assignments.map((a) => (
              <li key={a.assignment_id} className="flex items-start gap-2 text-sm">
                <FileText className="w-4 h-4 mt-0.5 shrink-0 text-blue-700" aria-hidden="true" />
                <span className="min-w-0 break-words">
                  <span className="text-gray-900">{a.title}</span>
                  <span className="block text-xs text-gray-500">{a.type} · due {formatDue(a.due_date)}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {onStartCheckin && (
        <div className="rounded-xl bg-gray-50 border border-gray-200 p-3 space-y-1.5">
          <button type="button" disabled={!!off || past} onClick={() => onStartCheckin(null, day)}
            className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-gray-900 text-white text-sm font-medium hover:bg-gray-800 disabled:opacity-40">
            <CalendarPlus className="w-4 h-4" aria-hidden="true" /> New check-in for this lesson day
          </button>
          <p className="text-xs text-gray-500">
            {off ? 'Pick a school day for a lesson.' : past ? 'This day has passed.' : 'Practice games, then a check-in due the evening before.'}
          </p>
        </div>
      )}
      {moving && (
        <p className="text-xs text-gray-500 inline-flex items-center gap-1.5"><Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> Saving the move…</p>
      )}
    </div>
  );
};

export default DayPanel;
