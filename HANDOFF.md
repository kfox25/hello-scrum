# Hello Scrum — Handoff Notes

## What this is
An AI Scrum operating model MVP. A Claude-powered agent picks raw ideas from a backlog,
writes user stories, implements them as patches to index.html, runs tests, sends to a
Hermes QA reviewer, and deploys to GitHub Pages on approval.

## Running it locally
```
cd C:\Users\Kevin\projects\hello-scrum
python server.py
# open http://localhost:5000
```
Requires: `pip install flask anthropic` and `ANTHROPIC_API_KEY` in environment.

## Key files
| File | Purpose |
|------|---------|
| `server.py` | Flask server, port 5000. Serves HTML pages, backlog API, SSE sprint stream |
| `agent.py` | Worker (claude-sonnet-4-6) + Hermes reviewer (claude-haiku-4-5-20251001) |
| `board.html` | Sprint board — drag items between Backlog and Sprint columns |
| `active.html` | Real-time view of current agent stage + live log panel |
| `audit.html` | History of all completed/failed items with diffs and Hermes verdicts |
| `workflow.html` | Visual diagram of the 6-step pipeline |
| `index.html` | The app being built by the agent (deployed to GitHub Pages) |
| `backlog.json` | Single data store — all items, statuses, audit fields |
| `active.json` | Written by agent at each stage; polled every 1.5s by active.html |
| `agent_log.json` | Live log lines written by agent; polled by active.html |
| `test.py` | Smoke tests run after each code change |
| `version.json` | Current version and changelog |

## Agent pipeline (agent.py)
pull → story → code → test → review → deploy

- **Worker**: claude-sonnet-4-6, max_tokens=8192
- **Hermes**: claude-haiku-4-5-20251001, max_tokens=256, sees up to 12000 chars of diff
- Agent returns `patches: [{find, replace}]` — NOT the full file — to avoid token limits
- Each `log()` call writes to stdout (SSE) AND appends to agent_log.json
- Diff is batch-logged via `log_lines()` (one file write for all lines)

## Board UI (board.html)
- Two columns: Backlog (pending, not in_sprint) | Sprint (in_sprint, any status)
- Drag pending items between columns and to reorder
- Add item input at top of backlog: ↑ Top or ↓ End
- Red ✕ to delete backlog items
- Start Sprint → POST /sprint/start (SSE stream)
- Complete Sprint → moves done/failed items back to backlog column

## Active page (active.html)
- Polls /active.json every 1.5s for stage updates
- Polls /agent-log every 1.5s for log lines
- Log panel: 5 lines tall, scrollable, color-coded (green=pass/add, red=fail/remove)
- Shows diff lines when agent hits code stage
- "✕ clear stuck state" button POSTs to /active/clear

## Known issues / recent fixes
- Patch-based approach added to fix JSON truncation as index.html grows
- agent_log.json cleared immediately on sprint start (server.py) to reset log panel
- flush=True required on log() calls — without it, SSE pipe stalls

## GitHub
- Repo: https://github.com/kfox25/hello-scrum
- Pages: https://kfox25.github.io/hello-scrum
- Every approved story auto-commits and pushes via git_push()

## Picking up where things left off
Run `git log --oneline` for the full history. All changes are committed.
