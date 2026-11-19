import React from 'react';
import AgentPanelShell from './AgentPanelShell';
import type { AgentPanelProps } from './registry';

/**
 * Materials update.  Owner: Teammate C.
 * TODO(Teammate C): instruction box -> POST /agents/materials/run, show the agent's todo
 * plan as it works, and a side-by-side diff view for each revision (the approve/reject
 * itself already works in the Approvals tab).  Run the Library demo first so there is
 * a document to revise.
 */
const MaterialsPanel: React.FC<AgentPanelProps> = ({ classId }) => (
  <AgentPanelShell agent="materials" classId={classId}>
    <div className="bg-white rounded-xl border border-gray-200 p-5 text-sm text-gray-600">
      Instruction box, plan view and diffs go here.
    </div>
  </AgentPanelShell>
);

export default MaterialsPanel;
