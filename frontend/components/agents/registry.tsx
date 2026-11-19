/**
 * The agent tabs in the teacher dashboard.  Layout.tsx and App.tsx read this list, so
 * adding or renaming a panel only touches this file and your own panel file.
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
}

export interface AgentTab {
  view: `AGENT_${string}`;
  label: string;
  component: React.FC<AgentPanelProps>;
}

export const AGENT_TABS: AgentTab[] = [
  { view: 'AGENT_LIBRARY', label: 'Library', component: LibraryPanel },          // Will
  { view: 'AGENT_SCHEDULER', label: 'Scheduler', component: SchedulerPanel },    // Teammate B
  { view: 'AGENT_MATERIALS', label: 'Update materials', component: MaterialsPanel }, // Teammate C
  { view: 'AGENT_GAMES', label: 'Study games', component: GamesPanel },          // Teammate D
  { view: 'AGENT_INSIGHTS', label: 'Insights', component: InsightsPanel },       // Teammate B
  { view: 'AGENT_APPROVALS', label: 'Approvals', component: ({ classId }) => <ApprovalsInbox classId={classId} /> },
];

export const findAgentTab = (view: string): AgentTab | undefined => AGENT_TABS.find((t) => t.view === view);
