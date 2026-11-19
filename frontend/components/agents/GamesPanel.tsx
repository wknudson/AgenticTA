import React, { useCallback, useEffect, useState } from 'react';
import { agentsFetch } from '../../services/agentsApi';
import AgentPanelShell from './AgentPanelShell';
import type { AgentPanelProps } from './registry';

/**
 * Study games (teacher side).  Owner: Teammate D.
 * TODO(Teammate D): topic picker -> POST /agents/games/run, preview of each game with the
 * reviewer's verdicts, and the STUDENT side: a game player (flashcards, matching, fill-in)
 * on the assignment page for status=published activities.
 */
interface Activity {
  activity_id: number;
  title: string;
  kind: string;
  status: string;
  attempts: number;
  items: Array<{ front: string; back: string }>;
}

const GamesPanel: React.FC<AgentPanelProps> = ({ classId }) => {
  const [acts, setActs] = useState<Activity[]>([]);
  const load = useCallback(() => {
    agentsFetch<{ activities: Activity[] }>(`/games/activities?class_id=${classId}`).then((r) => setActs(r.activities)).catch(() => {});
  }, [classId]);
  useEffect(load, [load]);

  return (
    <AgentPanelShell agent="games" classId={classId} onRunComplete={load}>
      <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-3">
        {acts.length === 0 && <p className="text-sm text-gray-600">No games yet.</p>}
        {acts.map((a) => (
          <div key={a.activity_id} className="border border-gray-200 rounded-lg p-3">
            <div className="flex justify-between text-sm">
              <span className="font-medium">{a.title} <span className="text-gray-500">({a.kind}, {a.attempts} round(s))</span></span>
              <span className={a.status === 'published' ? 'text-green-700' : 'text-amber-700'}>{a.status}</span>
            </div>
            <ul className="text-sm text-gray-700 mt-2 list-disc pl-5">
              {a.items.map((it, i) => <li key={i}>{it.front} → {it.back}</li>)}
            </ul>
          </div>
        ))}
      </div>
    </AgentPanelShell>
  );
};

export default GamesPanel;
