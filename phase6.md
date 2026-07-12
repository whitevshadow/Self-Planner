# Phase 6 — Smart Assistant

> Goal: the app remembers every meeting, nags with a purpose, knows what I should do right now, and shows me whether I'm actually getting better at planning.
> Parent doc: [Goal.md](Goal.md) · Builds on: [phase4.md](phase4.md), [phase5.md](phase5.md)

## Decisions (locked)

| Decision | Choice | Notes |
|----------|--------|-------|
| Meeting memory | **Vector search (pgvector)** | Embeddings stay inside Postgres — no new database. Chatbot gains a `search_history` tool. |
| Warnings | **Escalating** | Digest mention first → next-day direct chat alert with action options. Deferred here from Phase 5. |
| "What next?" | **Schedule + context aware** | Follows the plan but adapts to time-left, overdue pressure, and quick wins; always states its reason. |
| Tracking | **Weekly review + stats dashboard + estimate learning** | Meeting-commitment tracking skipped. |

## Scope

**In:**
- pgvector embeddings over segments, summaries, and decisions; semantic search API + chatbot tool
- Escalation engine for overdue/at-risk tasks with actionable chat alerts
- `what_next` chatbot tool (and dashboard button) with reasoned suggestions
- Actual-time capture from schedule block status changes
- Estimate learning: actuals history fed back into the estimation prompt
- `/stats` dashboard page
- Weekly review digest (Sunday evening, via the Phase 5 notification service)

**Out:**
- Meeting commitment tracking across recurring meetings (skipped by decision)
- Voice fingerprinting, team features, mobile app (still out of scope per Goal.md)

## Meeting memory (vector search)

**Embedding job:** after a meeting finishes processing, embed:
- each transcript segment (batched),
- the summary,
- each decision,
- each of my tasks (`kind='task'`, title + steps — required by estimate learning below).

Model: `LLM_MODEL_EMBED` on the base URL (OpenAI-compatible `/embeddings`). If the base URL has no embedding endpoint, fallback is local `sentence-transformers` (`all-MiniLM-L6-v2`) — config flag, same table either way.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE embeddings (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,             -- segment | summary | decision | task
    ref_id     UUID,                      -- segment/task id depending on kind
    text       TEXT NOT NULL,
    embedding  vector(1536) NOT NULL      -- dim from config; migration sets actual size
);
CREATE INDEX idx_embeddings_vec ON embeddings USING hnsw (embedding vector_cosine_ops);
```

**Search:** `GET /search?q=...` embeds the query, returns top-k matches with meeting title, date, speaker, and a link to the highlighted segment (reusing Phase 3's jump-to-segment). Chatbot tool `search_history` wraps the same call — "what did we decide about the auth deadline?" answers with quotes + meeting links, never from the model's imagination (answers must cite retrieved chunks).

**Backfill:** one-off job embeds all existing meetings on first run.

## Escalation engine

State machine per task, evaluated by the morning routine and after replans:

```
ok → mentioned          task appears overdue/at_risk in a digest (Phase 5 behavior)
mentioned → alerted     still overdue next morning → direct chat alert card with actions:
                          [Reschedule] [Lower priority] [Mark done] [Drop]
alerted → resolved      any action taken, or task completed
alerted → re-alerted    ignored for ESCALATION_REALERT_DAYS (default 2) → alert repeats,
                          now suggesting the most likely fix first (based on task age + load)
```

Rules:
- Alerts are actionable cards in chat (buttons call existing task/plan endpoints) — never bare nags.
- One escalation card per day maximum, bundling all alerted tasks — no alert storms.
- `tasks.escalation_state` + `escalated_at` columns track the state; taking any action resets it.

## "What should I do next?"

`what_next` — chatbot tool + a **Now** button on the dashboard.

Deterministic candidate builder first (no LLM): current/next scheduled block, overdue tasks, quick wins (tasks ≤ 30 min), and the free-time gap until the next GCal event. Then `LLM_MODEL_CHAT` picks **one** suggestion from those candidates and must state its reason:

> "You have 25 minutes before standup — finish 'Review Rahul's PR' (20 min, due today) instead of starting the auth block."

Rules:
- The LLM chooses only among presented candidates (same structure-over-vibes rule as the planner — it cannot invent a task).
- If the schedule is simply correct, it says so: "Stick with the plan: Authentication integration until 11:30."
- Response includes a one-tap `[Start]` action that marks the block in-progress.

## Progress tracking

### Actual-time capture
- Block marked `in_progress` → stamp `started_at`; marked `done` → stamp `finished_at`.
- `tasks.actual_minutes` = sum of its blocks' actual durations (manual correction allowed).
- No timers or idle detection — block status changes are the signal (you already tap start/done in the day plan).

### Estimate learning
- Estimation job (Phase 4, LLM job 4) prompt gains a **history section**: the 10 most similar completed tasks (via the embeddings table) with `estimated vs actual` minutes.
- Prompt instruction: calibrate against this history — e.g. "similar review tasks ran 1.6× over estimate."
- Learning is prompt-side only (no fine-tuning); `estimate_source='user'` overrides remain untouched.

### `/stats` dashboard (new page)
- **Completion**: tasks done per week, planned-vs-done ratio
- **On-time rate**: % of tasks finished before their due date
- **Estimate accuracy**: actual/estimated ratio distribution + trend line (is learning working?)
- **Load**: busiest weekdays, meeting hours vs task hours per week
- **Aging**: open tasks by age bucket, current escalation states
- All charts from SQL aggregates — no LLM involved.

### Weekly review digest
- New APScheduler job: Sunday `WEEKLY_REVIEW_TIME` (default 18:00), delivered via the Phase 5 notification service (chat card; future channels free).
- Content (LLM job 5, digest model, templated fallback as always): completed vs planned, slipped tasks and why (from escalation states), estimate accuracy callout, meeting load, next week's first look (due dates + already-scheduled blocks).

## Database changes

```sql
-- embeddings table + pgvector extension (above)

ALTER TABLE tasks ADD COLUMN escalation_state TEXT NOT NULL DEFAULT 'ok';
                  -- ok | mentioned | alerted | resolved
ALTER TABLE tasks ADD COLUMN escalated_at     TIMESTAMPTZ;
ALTER TABLE tasks ADD COLUMN actual_minutes   INT;

ALTER TABLE schedule_blocks ADD COLUMN started_at  TIMESTAMPTZ;
ALTER TABLE schedule_blocks ADD COLUMN finished_at TIMESTAMPTZ;
```

## Configuration (`backend/.env` additions)

```env
LLM_MODEL_EMBED=embedding-model    # or EMBED_LOCAL=true for sentence-transformers fallback
EMBED_DIM=1536                     # must match the chosen model
ESCALATION_REALERT_DAYS=2
WEEKLY_REVIEW_TIME=18:00           # Sundays
```

## API changes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/search?q=` | Semantic search over meeting history (top-k chunks + links). |
| POST | `/embeddings/backfill` | One-off embedding of existing meetings. |
| GET | `/what-next` | Candidate build + LLM pick; powers the tool and the dashboard button. |
| POST | `/tasks/{id}/escalation-action` | Reschedule / lower priority / done / drop from an alert card. |
| GET | `/stats/summary` · `/stats/estimates` · `/stats/load` | Aggregates for the stats page. |

Chatbot gains tools: `search_history`, `what_next` (escalation actions ride existing task endpoints).

## Frontend changes

- **Dashboard**: **Now** button (top of Today column) → what-next suggestion card with reason + `[Start]`; escalation alert cards render in chat with action buttons
- **`/stats` — new page**: the five chart groups above (recharts or chart.js)
- **Search**: global search box in the nav → results page with meeting/date/speaker context, click → highlighted segment
- **`/meetings/[id]`**: "Ask about this meeting" shortcut that opens chat pre-scoped to `search_history` on this meeting

## Build steps (in order)

1. **pgvector + embedding job**: extension, table, embed-on-process hook, backfill endpoint; verify base-URL embeddings or wire the local fallback
2. **Search**: `/search` endpoint + nav search UI + `search_history` chat tool (with citation-required prompt)
3. **Actual-time capture**: block timestamps, task actual_minutes rollup
4. **Escalation engine**: state machine in the morning routine, alert cards with action buttons, daily bundling
5. **What-next**: candidate builder, LLM pick with reason, dashboard button + chat tool
6. **Estimate learning**: similar-task history injection into the estimation prompt
7. **Stats**: aggregate endpoints + `/stats` page
8. **Weekly review**: Sunday job on the notification service
9. **End-to-end test**: ask "what did we decide about X?" → cited answer from an old meeting; let a task go overdue two mornings → escalation card with working buttons; complete tasks and watch estimate accuracy move on `/stats`; Sunday review arrives

## Definition of done

- [ ] "What did we decide about …?" returns real quotes with meeting links — answers cite retrieved chunks, never invent
- [ ] An overdue task escalates: digest mention → next-day actionable alert → re-alert after 2 ignored days; one card per day max
- [ ] Every escalation alert offers reschedule / deprioritize / done / drop, and the buttons work
- [ ] "What next?" gives one suggestion with a stated reason, chosen only from real candidates, with a working `[Start]`
- [ ] Actual minutes accumulate from block starts/finishes without any manual timing
- [ ] Estimation prompts include similar-task history, and `/stats` shows whether accuracy improves
- [ ] Weekly review lands in chat every Sunday evening with completed/slipped/accuracy/next-week sections
- [ ] Embedding model is swappable (base URL ↔ local) via `.env` alone
