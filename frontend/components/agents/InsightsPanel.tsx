import React from 'react';
import AgentPanelShell from './AgentPanelShell';
import type { AgentPanelProps } from './registry';

/**
 * "What students are struggling with" (misconception finder).  Owner: Teammate B.
 * TODO(Teammate B): one card per insight (GET /agents/misconceptions/insights) with
 * redacted example questions and buttons "Make a review game" (-> games) and "Draft a
 * review sheet" (-> materials).  Nothing runs until the teacher clicks.
 */
const InsightsPanel: React.FC<AgentPanelProps> = ({ classId }) => (
  <AgentPanelShell agent="misconceptions" classId={classId}>
    <div className="bg-white rounded-xl border border-gray-200 p-5 text-sm text-gray-600">
      Insight cards go here. The offline demo shows the redaction step working on the stored tutor chats.
    </div>
  </AgentPanelShell>
);

export default InsightsPanel;
