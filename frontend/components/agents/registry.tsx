/**
 * The agent tabs in the teacher dashboard.  Layout.tsx (via ClassTabs.tsx) and App.tsx read this
 * list, so adding or renaming a panel only touches this file and your own panel file.
 */
import React from 'react';
import ApprovalsInbox from './ApprovalsInbox';
import GamesPanel from './GamesPanel';
import InsightsPanel from './InsightsPanel';
import LibraryPanel from './LibraryPanel';
import MaterialsPanel from './MaterialsPanel';
import SchedulerPanel from './SchedulerPanel';

export interface AgentPanelProps {
  classId: number;
  teacherId: number;
  /** Navigation: open "New unit check-in" with this Library unit preselected (App.tsx wires it). */
  onStartCheckin?: (unit: string) => void;
}

/** Which class tab group a panel sits under (components/ClassTabs.tsx). */
export type AgentTabGroup = 'plan' | 'insights' | 'approvals';

export interface AgentTab {
  view: `AGENT_${string}`;
  label: string;
  component: React.FC<AgentPanelProps>;
  /** Defaults to 'plan'. */
  group?: AgentTabGroup;
}

export const AGENT_TABS: AgentTab[] = [
  { view: 'AGENT_LIBRARY', label: 'Library', component: LibraryPanel, group: 'plan' },          // Will
  { view: 'AGENT_SCHEDULER', label: 'Scheduler', component: SchedulerPanel, group: 'plan' },    // Teammate B
  { view: 'AGENT_MATERIALS', label: 'Update materials', component: MaterialsPanel, group: 'plan' }, // Teammate C
  { view: 'AGENT_GAMES', label: 'Study games', component: GamesPanel, group: 'plan' },          // Teammate D
  { view: 'AGENT_INSIGHTS', label: 'Insights', component: InsightsPanel, group: 'insights' },   // Teammate B
  {
    view: 'AGENT_APPROVALS',
    label: 'Approvals',
    component: ({ classId }) => <ApprovalsInbox classId={classId} />,
    group: 'approvals',
  },
];

export const findAgentTab = (view: string): AgentTab | undefined => AGENT_TABS.find((t) => t.view === view);
