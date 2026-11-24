/**
 * The class tab bar: five groups in a primary row, and the selected group's pages in a
 * secondary row. View names (ViewState) are unchanged; this only groups them.
 *
 *   Assignments | Plan (Library, Scheduler, Update materials, Study games)
 *   | Class (Class Info, Grades, Metrics) | Insights | Approvals (live pending count)
 *
 * Agent panels pick their group in components/agents/registry.tsx (default: Plan).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ClipboardList, Inbox, Layers, Lightbulb, Users, type LucideIcon } from 'lucide-react';
import type { ViewState } from '../types';
import { AGENT_TABS, type AgentTabGroup } from './agents/registry';
import { countPendingApprovals } from '../services/classOverviewApi';

type GroupId = 'assignments' | 'plan' | 'class' | 'insights' | 'approvals';

interface SubTab {
  view: ViewState;
  label: string;
}

interface TabGroup {
  id: GroupId;
  label: string;
  icon: LucideIcon;
  tabs: SubTab[];
  /** Other views that keep this group highlighted (e.g. an assignment's detail page). */
  alsoActiveFor?: ViewState[];
}

const agentTabs = (group: AgentTabGroup): SubTab[] =>
  AGENT_TABS.filter((t) => (t.group ?? 'plan') === group).map((t) => ({ view: t.view, label: t.label }));

const ALL_GROUPS: TabGroup[] = [
  {
    id: 'assignments',
    label: 'Assignments',
    icon: ClipboardList,
    tabs: [{ view: 'ASSIGNMENT_LIST', label: 'Assignments' }],
    alsoActiveFor: ['ASSIGNMENT_EDIT', 'ASSIGNMENT_VIEW', 'ASSIGNMENT_CREATE_SUCCESS', 'CHECKIN_NEW', 'VIEW_AS_STUDENT'],
  },
  { id: 'plan', label: 'Plan', icon: Layers, tabs: agentTabs('plan') },
  {
    id: 'class',
    label: 'Class',
    icon: Users,
    tabs: [
      { view: 'CLASS_INFO', label: 'Class Info' },
      { view: 'GRADES', label: 'Grades' },
      { view: 'METRICS', label: 'Metrics' },
    ],
  },
  { id: 'insights', label: 'Insights', icon: Lightbulb, tabs: agentTabs('insights') },
  { id: 'approvals', label: 'Approvals', icon: Inbox, tabs: agentTabs('approvals') },
];

export const CLASS_TAB_GROUPS: TabGroup[] = ALL_GROUPS.filter((g) => g.tabs.length > 0);

export function groupForView(view: ViewState): TabGroup | undefined {
  return CLASS_TAB_GROUPS.find((g) => g.tabs.some((t) => t.view === view) || g.alsoActiveFor?.includes(view));
}

const POLL_MS = 30_000;

/**
 * Pending approvals for the class: refreshed on class change, whenever `refreshKey` changes
 * (the current view, so it updates after deciding or creating an approval), on window focus,
 * and every 30 s while the page is visible. null = unknown (service down, or still loading).
 */
export function usePendingApprovals(classId: number, refreshKey?: unknown): number | null {
  const [count, setCount] = useState<number | null>(null);
  const seq = useRef(0);

  const refresh = useCallback(() => {
    const mine = ++seq.current;
    countPendingApprovals(classId)
      .then((n) => { if (seq.current === mine) setCount(n); })
      .catch(() => { if (seq.current === mine) setCount(null); });
  }, [classId]);

  useEffect(() => { setCount(null); }, [classId]);
  useEffect(() => { refresh(); }, [refresh, refreshKey]);

  useEffect(() => {
    const visible = () => document.visibilityState === 'visible';
    const onFocus = () => refresh();
    const onVisibility = () => { if (visible()) refresh(); };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibility);
    const timer = window.setInterval(() => { if (visible()) refresh(); }, POLL_MS);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibility);
      window.clearInterval(timer);
    };
  }, [refresh]);

  return count;
}

interface ClassTabsProps {
  classId: number;
  currentView: ViewState;
  onViewChange: (view: ViewState) => void;
}

const focusRing = 'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ba3638] focus-visible:ring-offset-1';

const ClassTabs: React.FC<ClassTabsProps> = ({ classId, currentView, onViewChange }) => {
  const pending = usePendingApprovals(classId, currentView);
  const active = groupForView(currentView);
  // Clicking a group goes back to the page you last had open in it (first page by default).
  const lastPage = useRef<Partial<Record<GroupId, ViewState>>>({});
  useEffect(() => {
    if (active && active.tabs.some((t) => t.view === currentView)) lastPage.current[active.id] = currentView;
  }, [active, currentView]);

  const badgeText = (n: number) => (n > 99 ? '99+' : String(n));

  return (
    <div className="bg-gray-50 border-b border-gray-100">
      <nav aria-label="Class sections" className="px-4 sm:px-6 lg:px-8 pt-2 pb-2">
        {/* Phones: all five groups share one row (icon over a short label), sized to their labels. */}
        <ul className="flex gap-0.5 sm:flex-wrap sm:gap-1">
          {CLASS_TAB_GROUPS.map((g) => {
            const isActive = active?.id === g.id;
            const Icon = g.icon;
            const badge = g.id === 'approvals' && pending ? pending : 0;
            return (
              <li key={g.id} className="flex-auto sm:flex-none">
                <button
                  type="button"
                  onClick={() => onViewChange(lastPage.current[g.id] ?? g.tabs[0].view)}
                  aria-current={isActive ? 'page' : undefined}
                  className={`w-full flex flex-col items-center gap-0.5 rounded-lg border px-1.5 py-1.5 text-[11px] leading-tight font-medium transition-colors sm:w-auto sm:flex-row sm:gap-2 sm:px-4 sm:py-2 sm:text-sm ${focusRing} ${
                    isActive
                      ? 'bg-white text-black shadow-sm border-gray-200'
                      : 'border-transparent text-gray-600 hover:text-black hover:bg-white/70'
                  }`}
                >
                  <span className="relative inline-flex">
                    <Icon className="w-5 h-5 sm:w-4 sm:h-4" aria-hidden="true" />
                    {badge > 0 && (
                      <span
                        aria-hidden="true"
                        className="sm:hidden absolute -top-1.5 -right-2.5 min-w-[1.1rem] h-[1.1rem] px-1 rounded-full bg-[#ba3638] text-white text-[10px] font-semibold leading-[1.1rem] text-center"
                      >
                        {badgeText(badge)}
                      </span>
                    )}
                  </span>
                  <span className="whitespace-nowrap">{g.label}</span>
                  {badge > 0 && (
                    <>
                      <span
                        aria-hidden="true"
                        className="hidden sm:inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-[#ba3638] text-white text-xs font-semibold"
                      >
                        {badgeText(badge)}
                      </span>
                      <span className="sr-only">, {badge} pending</span>
                    </>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      {active && active.tabs.length > 1 && (
        <nav aria-label={`${active.label} pages`} className="px-4 sm:px-6 lg:px-8 pb-2">
          <ul className="flex flex-wrap gap-1 border-t border-gray-200 pt-2">
            {active.tabs.map((t) => {
              const isCurrent = currentView === t.view;
              return (
                <li key={t.view}>
                  <button
                    type="button"
                    onClick={() => onViewChange(t.view)}
                    aria-current={isCurrent ? 'page' : undefined}
                    className={`px-3 py-1.5 rounded-full text-[13px] sm:text-sm font-medium whitespace-nowrap transition-colors ${focusRing} ${
                      isCurrent ? 'bg-gray-900 text-white' : 'text-gray-600 hover:text-black hover:bg-white'
                    }`}
                  >
                    {t.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
    </div>
  );
};

export default ClassTabs;
