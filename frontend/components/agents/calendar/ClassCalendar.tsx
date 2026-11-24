import React, { useMemo, useRef, useState } from 'react';
import { BookOpen, ChevronLeft, ChevronRight, Clock, FileText, Hourglass } from 'lucide-react';
import type { FeedAssignment, FeedCheckin, FeedDraft, FeedEvent } from '../../../services/schedulerFeedApi';
import {
  KINDS,
  Term,
  addMonths,
  dayOffReason,
  isWeekend,
  kindStyle,
  longDate,
  monthGrid,
  monthOf,
  monthTitle,
  shortDate,
  todayISO,
} from './calendarUtils';
import {
  CHECKIN_PALETTE,
  DayItems,
  buildDayIndex,
  checkinColors,
  daysBetween,
  emptyDay,
  practiceLanes,
  practiceWindow,
} from './classCalendarData';

/** What is being dragged: a scheduler event chip, or a check-in's lesson chip. */
export type CalendarDrag = { type: 'event'; event: FeedEvent } | { type: 'checkin'; checkin: FeedCheckin };

interface Props {
  month: string; // 'YYYY-MM-01'
  onMonthChange: (month: string) => void;
  term: Term | null;
  events: FeedEvent[];
  checkins: FeedCheckin[];
  drafts: FeedDraft[];
  assignments: FeedAssignment[];
  /** Dates with a rule problem (conflict) are outlined in red. */
  problemDates?: Set<string>;
  selected: string | null;
  onSelect: (day: string) => void;
  /** A chip was dropped on another school day. Without it nothing can be dragged. */
  onMove?: (item: CalendarDrag, day: string) => void;
  /** A drop was refused (weekend, day off, outside the term): the reason, to show the teacher. */
  onRefuse?: (message: string) => void;
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MAX_CHIPS = 3;
const MAX_LANES = 3;
// Practice bands sit under the day number: cell padding (4px phone / 6px sm) + the 24px number row.
const BAND_TOP = { phone: 28, wide: 30 };
const LANE = { phone: 6, wide: 16 };

const dragTitle = (item: CalendarDrag) => (item.type === 'event' ? item.event.title : item.checkin.title);
const dragDay = (item: CalendarDrag) => (item.type === 'event' ? item.event.date : (item.checkin.lesson_date ?? '').slice(0, 10));

const chipBase = 'flex items-center gap-1 min-w-0 rounded-md border px-1.5 py-0.5 text-[11px] leading-tight';

const ClassCalendar: React.FC<Props> = ({
  month, onMonthChange, term, events, checkins, drafts, assignments, problemDates, selected, onSelect, onMove, onRefuse,
}) => {
  const days = useMemo(() => monthGrid(month), [month]);
  const weeks = useMemo(() => {
    const out: string[][] = [];
    for (let i = 0; i < days.length; i += 7) out.push(days.slice(i, i + 7));
    return out;
  }, [days]);
  const index = useMemo(() => buildDayIndex({ events, checkins, drafts, assignments }), [events, checkins, drafts, assignments]);
  const lanes = useMemo(() => practiceLanes(checkins), [checkins]);
  const colors = useMemo(() => checkinColors(checkins), [checkins]);
  const holidays = useMemo(() => Object.fromEntries((term?.holidays ?? []).map((h) => [h.date, h.label])), [term]);
  const today = todayISO();
  const inMonth = (d: string) => d.slice(0, 7) === month.slice(0, 7);
  const inTerm = (d: string) => !term?.term_start || (d >= term.term_start && d <= term.term_end);
  const colorOf = (id: number) => colors.get(id) ?? CHECKIN_PALETTE[0];

  // Drag and drop (desktop chips only; the day panel is the keyboard and phone alternative).
  const dragRef = useRef<CalendarDrag | null>(null);
  const droppedRef = useRef(false);
  const overRef = useRef<{ day: string; reason: string | null } | null>(null);
  const [dragging, setDragging] = useState<CalendarDrag | null>(null);
  const [over, setOver] = useState<{ day: string; reason: string | null } | null>(null);

  const refusal = (item: CalendarDrag, day: string) => {
    if (day === dragDay(item)) return null; // back where it started: not a refusal, just no move
    const reason = dayOffReason(day, term);
    return reason ? `Can't move "${dragTitle(item)}" there: ${reason}` : null;
  };
  const endDrag = () => {
    dragRef.current = null; overRef.current = null;
    setDragging(null); setOver(null);
  };
  const startDrag = (e: React.DragEvent, item: CalendarDrag) => {
    e.stopPropagation();
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragTitle(item)); // Firefox needs data to start a drag
    dragRef.current = item; droppedRef.current = false;
    setDragging(item);
  };
  const onDragEnd = () => {
    const last = overRef.current;
    if (!droppedRef.current && last?.reason) onRefuse?.(last.reason);
    endDrag();
  };
  const onDragOver = (e: React.DragEvent, day: string) => {
    const item = dragRef.current;
    if (!item) return;
    const reason = refusal(item, day);
    if (!reason) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; }
    if (overRef.current?.day !== day) {
      overRef.current = { day, reason };
      setOver(overRef.current);
    }
  };
  const onDrop = (e: React.DragEvent, day: string) => {
    e.preventDefault();
    const item = dragRef.current;
    droppedRef.current = true;
    endDrag();
    if (!item || dragDay(item) === day) return;
    const reason = refusal(item, day);
    if (reason) onRefuse?.(reason);
    else onMove?.(item, day);
  };
  const draggable = (item: CalendarDrag) => (onMove ? {
    draggable: true,
    onDragStart: (e: React.DragEvent) => startDrag(e, item),
    onDragEnd,
    title: `${dragTitle(item)}${item.type === 'event' && item.event.status === 'proposed' ? ' (waiting for approval)' : ''}: drag to another school day to move it`,
  } : {});

  const dayLabel = (d: string, items: DayItems, holiday: string | undefined, marker: string | null) => {
    const drafted = items.draftLessons.length + items.draftDues.length;
    return [
      longDate(d), holiday && `no school: ${holiday}`, marker, !inTerm(d) && 'outside the term',
      ...items.lessons.map((c) => `lesson for ${c.title}`),
      ...items.dues.map((c) => `${c.title} due`),
      items.events.length > 0 && `${items.events.length} event${items.events.length === 1 ? '' : 's'}`,
      items.assignments.length > 0 && `${items.assignments.length} assignment${items.assignments.length === 1 ? '' : 's'} due`,
      drafted > 0 && `${drafted} draft check-in item${drafted === 1 ? '' : 's'} waiting for approval`,
      items.windows.length > 0 && `practice open for ${items.windows.length} check-in${items.windows.length === 1 ? '' : 's'}`,
      problemDates?.has(d) && 'has a conflict',
    ].filter(Boolean).join(', ');
  };

  const renderChips = (items: DayItems) => {
    const chips: React.ReactNode[] = [];
    for (const c of items.lessons) {
      const color = colorOf(c.assignment_id);
      chips.push(
        <div key={`l${c.assignment_id}`} {...draggable({ type: 'checkin', checkin: c })}
          className={`${chipBase} ${color.chip} font-medium ${onMove ? 'cursor-grab active:cursor-grabbing' : ''} ${c.status === 'closed' ? 'opacity-70' : ''}`}>
          <BookOpen className="w-3 h-3 shrink-0" aria-hidden="true" />
          <span className="truncate flex-1">{c.title}</span>
          {c.counts.total > 0 && <span className="shrink-0 tabular-nums opacity-80">{c.counts.complete}/{c.counts.total}</span>}
        </div>,
      );
    }
    for (const dr of items.draftLessons) {
      chips.push(
        <div key={`dl${dr.package_id}`} title={`${dr.title} (draft, waiting for approval)`}
          className={`${chipBase} border-dashed border-gray-400 bg-white text-gray-700 italic`}>
          <Hourglass className="w-3 h-3 shrink-0" aria-hidden="true" />
          <span className="truncate">{dr.title}</span>
        </div>,
      );
    }
    for (const c of items.dues) {
      const color = colorOf(c.assignment_id);
      chips.push(
        <div key={`d${c.assignment_id}`} title={`${c.title} due`}
          className={`${chipBase} bg-white ${color.chip.split(' ').filter((k) => !k.startsWith('bg-')).join(' ')}`}>
          <Clock className="w-3 h-3 shrink-0" aria-hidden="true" />
          <span className="truncate">Due · {c.title}</span>
        </div>,
      );
    }
    for (const dr of items.draftDues) {
      chips.push(
        <div key={`dd${dr.package_id}`} title={`${dr.title} due (draft, waiting for approval)`}
          className={`${chipBase} border-dashed border-gray-400 bg-white text-gray-600 italic`}>
          <Clock className="w-3 h-3 shrink-0" aria-hidden="true" />
          <span className="truncate">Due · {dr.title}</span>
        </div>,
      );
    }
    for (const e of items.events) {
      chips.push(
        <div key={`e${e.event_id}`} {...draggable({ type: 'event', event: e })}
          className={[chipBase, kindStyle(e.kind).chip, e.status === 'proposed' ? 'border-dashed italic opacity-90' : '',
            onMove ? 'cursor-grab active:cursor-grabbing' : ''].join(' ')}>
          <span className="truncate">{e.title}</span>
        </div>,
      );
    }
    for (const a of items.assignments) {
      chips.push(
        <div key={`a${a.assignment_id}`} title={`${a.title} due`} className={`${chipBase} ${kindStyle('assignment_due').chip}`}>
          <FileText className="w-3 h-3 shrink-0" aria-hidden="true" />
          <span className="truncate">{a.title}</span>
        </div>,
      );
    }
    const shown = chips.slice(0, MAX_CHIPS);
    return (
      <span className="mt-1 hidden sm:flex flex-col gap-0.5 min-w-0">
        {shown}
        {chips.length > MAX_CHIPS && (
          <span className="text-[11px] text-gray-500 px-1">+{chips.length - MAX_CHIPS} more</span>
        )}
      </span>
    );
  };

  const renderDots = (items: DayItems) => {
    const dots: Array<{ key: string; cls: string }> = [
      ...items.lessons.map((c) => ({ key: `l${c.assignment_id}`, cls: colorOf(c.assignment_id).dot })),
      ...items.dues.map((c) => ({ key: `d${c.assignment_id}`, cls: `bg-white ring-2 ring-inset ${colorOf(c.assignment_id).dot.replace('bg-', 'ring-')}` })),
      ...items.events.map((e) => ({ key: `e${e.event_id}`, cls: kindStyle(e.kind).dot })),
      ...items.assignments.map((a) => ({ key: `a${a.assignment_id}`, cls: kindStyle('assignment_due').dot })),
      ...[...items.draftLessons, ...items.draftDues].map((d, i) => ({ key: `dr${d.package_id}-${i}`, cls: 'bg-white border border-dashed border-gray-500' })),
    ];
    if (!dots.length) return null;
    return (
      <span className="flex flex-wrap gap-0.5 mt-0.5 sm:hidden" aria-hidden="true">
        {dots.slice(0, 5).map((d) => <span key={d.key} className={`w-1.5 h-1.5 rounded-full ${d.cls}`} />)}
      </span>
    );
  };

  const renderBands = (week: string[], wide: boolean) => {
    const first = week[0];
    const last = week[6];
    const segments = checkins.flatMap((c) => {
      const w = practiceWindow(c);
      const lane = lanes.get(c.assignment_id) ?? 0;
      if (!w || lane >= MAX_LANES || w.end < first || w.start > last) return [];
      const startsHere = w.start >= first;
      const endsHere = w.end <= last;
      const col = startsHere ? daysBetween(first, w.start) : 0;
      const endCol = endsHere ? daysBetween(first, w.end) : 6;
      return [{ c, lane, col, span: endCol - col + 1, startsHere, endsHere }];
    });
    if (!segments.length) return null;
    const top = wide ? BAND_TOP.wide : BAND_TOP.phone;
    const laneH = wide ? LANE.wide : LANE.phone;
    return (
      // Above every cell (a selected or focused cell is raised), and click/drop-through.
      <div aria-hidden="true" className={`pointer-events-none absolute inset-x-0 z-[6] ${wide ? 'hidden sm:block' : 'sm:hidden'}`} style={{ top }}>
        {segments.map(({ c, lane, col, span, startsHere, endsHere }) => {
          const inset = (startsHere ? 4 : 0) + (endsHere ? 4 : 0);
          return (
            <div key={c.assignment_id}
              className={[
                'absolute overflow-hidden whitespace-nowrap',
                colorOf(c.assignment_id).band,
                startsHere ? 'rounded-l-full' : '', endsHere ? 'rounded-r-full' : '',
                c.status === 'closed' ? 'opacity-50' : '',
              ].join(' ')}
              style={{
                top: lane * laneH,
                height: laneH - 2,
                left: `calc(${(col / 7) * 100}% + ${startsHere ? 4 : 0}px)`,
                width: `calc(${(span / 7) * 100}% - ${inset}px)`,
              }}>
              {wide && (
                <span className="block truncate px-2 text-[10px] leading-[14px] font-medium">Practice · {c.title}</span>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  const dragHint = !dragging
    ? (onMove ? 'Drag a lesson or an event to another school day to move it, or click a day to change it there.' : 'Saving…')
    : over?.reason
      ?? (over && over.day !== dragDay(dragging) ? `Drop to move "${dragTitle(dragging)}" to ${shortDate(over.day)}.`
        : `Moving "${dragTitle(dragging)}": drop it on another school day.`);
  const anyDashed = events.some((e) => e.status === 'proposed') || drafts.length > 0;

  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-2 mb-2">
        <h3 className="text-lg font-semibold text-gray-900" aria-live="polite">{monthTitle(month)}</h3>
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => onMonthChange(monthOf(today))}
            className="px-2.5 py-1 text-sm rounded-lg border border-gray-300 hover:bg-gray-50">Today</button>
          <button type="button" aria-label="Previous month" onClick={() => onMonthChange(addMonths(month, -1))}
            className="p-1.5 rounded-lg hover:bg-gray-100"><ChevronLeft className="w-4 h-4" /></button>
          <button type="button" aria-label="Next month" onClick={() => onMonthChange(addMonths(month, 1))}
            className="p-1.5 rounded-lg hover:bg-gray-100"><ChevronRight className="w-4 h-4" /></button>
        </div>
      </div>
      <p aria-live="polite" className={`hidden sm:block min-h-[1.25rem] mb-2 text-xs truncate ${dragging && over?.reason ? 'text-amber-800 font-medium' : 'text-gray-500'}`}>
        {dragHint}
      </p>

      <div className="grid grid-cols-7 text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1">
        {WEEKDAYS.map((d) => <div key={d} className="px-1 text-center"><span className="sm:hidden">{d[0]}</span><span className="hidden sm:inline">{d}</span></div>)}
      </div>

      <div className="flex flex-col gap-px bg-gray-200 border border-gray-200 rounded-xl overflow-hidden"
        onDragLeave={(e) => {
          // Left the grid: a release out there isn't a refused drop on the last day hovered.
          if (dragRef.current && !e.currentTarget.contains(e.relatedTarget as Node | null)) { overRef.current = null; setOver(null); }
        }}>
        {weeks.map((week) => {
          const weekLanes = Math.min(MAX_LANES, Math.max(0, ...checkins.map((c) => {
            const w = practiceWindow(c);
            return w && w.end >= week[0] && w.start <= week[6] ? (lanes.get(c.assignment_id) ?? 0) + 1 : 0;
          })));
          return (
            <div key={week[0]} className="relative grid grid-cols-7 gap-px">
              {week.map((d) => {
                const items = index[d] ?? emptyDay();
                const holiday = holidays[d];
                const quiet = isWeekend(d) || !inTerm(d);
                const conflict = problemDates?.has(d);
                const isSelected = selected === d;
                const marker = term?.term_start === d ? 'First day' : term?.term_end === d ? 'Last day' : null;
                const hidden = items.windows.filter((c) => (lanes.get(c.assignment_id) ?? 0) >= MAX_LANES).length;
                const isOver = !!dragging && over?.day === d;
                // One background and one ring at a time (Tailwind's CSS order, not class order, decides clashes).
                const bg = isOver ? (over?.reason ? 'bg-gray-100 cursor-not-allowed' : 'bg-red-50')
                  : holiday ? 'bg-amber-50 hover:bg-amber-100/70' : quiet ? 'bg-gray-50 hover:bg-gray-100' : 'bg-white hover:bg-gray-50';
                const ring = isOver ? `ring-2 ring-inset z-[2] ${over?.reason ? 'ring-amber-400' : 'ring-[#ba3638]'}`
                  : isSelected ? 'ring-2 ring-inset ring-gray-900 z-[1]'
                    : conflict ? 'ring-2 ring-inset ring-red-500 z-[1]' : '';
                return (
                  <div
                    key={d}
                    role="button"
                    tabIndex={0}
                    aria-label={dayLabel(d, items, holiday, marker)}
                    aria-pressed={isSelected}
                    onClick={() => onSelect(d)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(d); } }}
                    onDragOver={(e) => onDragOver(e, d)}
                    onDrop={(e) => onDrop(e, d)}
                    className={[
                      'relative flex flex-col items-stretch justify-start text-left min-w-0 cursor-pointer select-none',
                      'focus:outline-none focus-visible:z-[4] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[#ba3638]',
                      'min-h-[56px] sm:min-h-[104px] p-1 sm:p-1.5',
                      bg, ring,
                      !inMonth(d) ? 'opacity-40' : '',
                    ].join(' ')}
                  >
                    <span className="flex items-center gap-1 min-w-0 h-6">
                      <span className={[
                        'inline-flex shrink-0 items-center justify-center text-xs w-6 h-6 rounded-full',
                        d === today ? 'bg-[#ba3638] text-white font-bold' : quiet ? 'text-gray-400' : 'text-gray-700',
                      ].join(' ')}>
                        {Number(d.slice(8))}
                      </span>
                      {(holiday || marker) && (
                        <span className={`hidden sm:block flex-1 min-w-0 truncate text-[10px] leading-tight font-medium ${holiday ? 'text-amber-800' : 'text-gray-500'}`}>
                          {holiday ?? marker}
                        </span>
                      )}
                      {hidden > 0 && (
                        <span className="ml-auto shrink-0 text-[10px] text-gray-500" title={`${hidden} more practice window${hidden === 1 ? '' : 's'} open`}>
                          +{hidden}
                        </span>
                      )}
                    </span>
                    <span aria-hidden="true" className="block sm:hidden shrink-0" style={{ height: weekLanes * LANE.phone }} />
                    <span aria-hidden="true" className="hidden sm:block shrink-0" style={{ height: weekLanes * LANE.wide }} />
                    {renderDots(items)}
                    {renderChips(items)}
                  </div>
                );
              })}
              {renderBands(week, false)}
              {renderBands(week, true)}
            </div>
          );
        })}
      </div>

      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600" aria-label="Legend">
        <li className="flex items-center gap-1.5"><span className="w-5 h-2 rounded-full bg-violet-200" />Practice window</li>
        <li className="flex items-center gap-1.5"><BookOpen className="w-3.5 h-3.5 text-violet-700" aria-hidden="true" />Lesson day (students done / total)</li>
        <li className="flex items-center gap-1.5"><Clock className="w-3.5 h-3.5 text-violet-700" aria-hidden="true" />Check-in due</li>
        <li className="flex items-center gap-1.5"><FileText className="w-3.5 h-3.5 text-blue-700" aria-hidden="true" />Graded assignment due</li>
        {KINDS.map((k) => (
          <li key={k.value} className="flex items-center gap-1.5">
            <span className={`w-2.5 h-2.5 rounded-full ${kindStyle(k.value).dot}`} />{k.label}
          </li>
        ))}
        <li className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-amber-100 border border-amber-300" />No school</li>
        <li className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-gray-100 border border-gray-300" />Weekend or outside the term</li>
        {anyDashed && (
          <li className="flex items-center gap-1.5"><span className="w-4 h-2.5 rounded-sm border border-dashed border-gray-500" />Waiting for approval</li>
        )}
        {problemDates && problemDates.size > 0 && (
          <li className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm ring-2 ring-red-500" />Conflict</li>
        )}
      </ul>
    </div>
  );
};

export default ClassCalendar;
