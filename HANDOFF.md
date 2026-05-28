# Hello Scrum — Handoff Notes

## What this is
An AI Scrum operating model MVP. A Claude-powered agent picks raw ideas from a backlog,
writes user stories, implements them as patches to index.html, runs tests, sends to a
Hermes QA reviewer, and deploys to GitHub Pages on approval. After each sprint, a retro
agent analyses the completed work and synthesises coding and AC wisdom for future sprints.

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
| `server.py` | Flask server, port 5000. Serves HTML pages and all APIs |
| `agent.py` | Worker (claude-sonnet-4-6) + Hermes reviewer (claude-haiku-4-5-20251001) + retro + wisdom |
| `board.html` | Sprint board — drag items between Backlog and Sprint columns |
| `active.html` | Real-time work card + pipeline dots + live activity stream |
| `retro.html` | Retrospective history and wisdom browser |
| `health.html` | Sprint health diagnostics |
| `audit.html` | Full history of completed/failed items with diffs and Hermes verdicts |
| `workflow.html` | Visual diagram of the pipeline |
| `index.html` | The app being built by the agent (deployed to GitHub Pages) |
| `index_baseline.html` | Minimal reset state for index.html |
| `sdlc_pipeline.json` | Single data store — all items, statuses, stage_times, audit fields |
| `active.json` | Written by agent at each stage; polled every 1.5s by active.html |
| `agent_log.json` | Live log lines written by agent; polled by active.html |
| `retrospective.json` | Sprint retro summaries, findings, sprint-scoped wisdom |
| `coding_wisdom.json` | Global coding wisdom synthesised across all sprints |
| `ac_wisdom.json` | Global AC wisdom synthesised across all sprints |
| `test.py` | Smoke tests run after each code change |
| `version.json` | Current version and changelog |

## Agent pipeline (agent.py)
pull → story → code → test → code_review → ac_check → deploy → done

- **Worker**: claude-sonnet-4-6, max_tokens=8192
- **Hermes**: claude-haiku-4-5-20251001, max_tokens=256, runs code_review and ac_check separately
- Agent returns `patches: [{find, replace}]` — NOT the full file — to avoid token limits
- Each `log()` call writes to stdout AND appends to agent_log.json
- Diff is batch-logged via `log_lines()` (one file write for all lines)

## Sprint retro (agent.py — run_retro)
Runs inline after the sprint loop completes. Five stages tracked in active.json:
retro → sprint_coding_wisdom → sprint_ac_wisdom → coding_wisdom → ac_wisdom

- Calls `_call_retro_api()` to generate summary + findings
- Extracts sprint-scoped wisdom bullets (coding + AC) from the sprint items
- Synthesises global `coding_wisdom.json` and `ac_wisdom.json`
- Stores sprint wisdom in `retrospective.json` under `sprint_coding_wisdom` / `sprint_ac_wisdom`

## Board UI (board.html)
- Two columns: Backlog (pending, not in_sprint) | Sprint (in_sprint, any status)
- Drag pending items between columns and to reorder
- Add item input at top of backlog: ↑ Top or ↓ End
- Red ✕ to delete backlog items
- Start Sprint → POST /sprint/start

## Active page (active.html)
- **Work card** (left panel): shows current item with pipeline dots, story text, AC, timer, Hermes verdict, status line. All sections pre-allocated to fixed heights — no layout shifts.
- **Activity stream** (right panel): live log lines, colour-coded, grouped by stage headers
- Polls `/active.json` every 1.5s for stage updates
- Polls `/agent-log` every 1.5s for log lines
- **Sprint backlog** (bottom-left): shows all sprint items with live dot states. Click a story to freeze the work card at that story's final state. Click retro row to show retro work card.
- **Retro work card**: 5 pipeline dots (Retro · Sprint Coding · Sprint AC · Coding Wisdom · AC Wisdom). Dot activates only when `active.json` confirms retro is running — not on allTerminal alone.
- Clicking a story or the retro row freezes the work card; clicking elsewhere restores live state.

## Baseline workflow
1. Click "Restore to Baseline" on board.html or health.html — resets index.html and commits to git
2. Add sprint stories (via add_sprint_stories.py or board.html)
3. Click "Start Sprint" on board.html
4. Sprint + retro complete automatically
5. Repeat from step 1

## GitHub
- Repo: https://github.com/kfox25/hello-scrum
- Pages: https://kfox25.github.io/hello-scrum
- Every approved story auto-commits and pushes via git_push()

## Picking up where things left off
Run `git log --oneline` for the full history. All changes are committed.
