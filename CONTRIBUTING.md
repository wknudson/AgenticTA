# Team workflow

## Who owns what

| Owner | Python | Frontend panel |
|---|---|---|
| Will | `agents/app/agents/filing`, `agents/app/agents/tutor`, `agents/app/shared/library.py` | `LibraryPanel.tsx` |
| Teammate B | `agents/app/agents/scheduler`, `agents/app/agents/misconceptions` | `SchedulerPanel.tsx`, `InsightsPanel.tsx` |
| Teammate C | `agents/app/agents/materials` | `MaterialsPanel.tsx` |
| Teammate D | `agents/app/agents/games` | `GamesPanel.tsx` (+ student game player) |

Shared files (`agents/app/shared/*` except `library.py`, `agents/config.yaml`, `frontend/components/agents/registry.tsx`, `AgentPanelShell.tsx`, `ApprovalsInbox.tsx`): **change them in a small PR of their own** and tell the team, because everyone depends on them.

## Branches and PRs

1. `git switch main && git pull`
2. `git switch -c <your-agent>/<what>`, e.g. `scheduler/term-form`
3. Commit small, push, open a PR into `main`, and ask one teammate to review
4. Before opening the PR: `npm run test:agents` passes, and your panel's offline demo still works

## Secrets and data

- Never commit `.env`, `data/`, or real student information. `.gitignore` covers the first two.
- Sample teacher materials for testing: put them in your own `data/files` through the Library tab, not in git.
