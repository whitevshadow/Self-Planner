# Phase 5 — Notion Sync & Notifications

> Goal: my tasks and meeting summaries live in Notion too (completion syncs both ways), and the app proactively tells me what matters — morning plan, meeting digests, evening wrap-up.
> Parent doc: [Goal.md](Goal.md) · Builds on: [phase4.md](phase4.md)

## Decisions (locked)

| Decision | Choice | Notes |
|----------|--------|-------|
| Integrations | **Notion only** | Todoist, Slack, and Email skipped. Google Calendar already done in Phase 4. |
| Sync mode | **Two-way completion sync** | Tasks pushed to a Notion database; checking one done in Notion marks it done in-app (poll-based). Same philosophy as GCal two-way. |
| Notifications | **Morning plan, meeting processed, evening wrap-up** | At-risk/overdue alerts deferred to Phase 6 (fits its "overdue warnings" scope). |
| Delivery channel | **In-app chat feed** | No Slack/Email chosen, so digests post as assistant messages in chat. Built behind a channel abstraction — adding Slack/Email later is a new adapter, not a redesign. |
| Follow-up model | **Just for me** | No team-facing follow-up messages. The "meeting processed" digest *is* the follow-up; Goal.md's follow-up model shrinks to digest generation (LLM job 5). |

## Scope

**In:**
- Notion connection (integration token) + settings UI
- Tasks → Notion database (my tasks only), with status, due date, priority, meeting link
- Meeting summaries → Notion pages (summary, decisions, my tasks) in a "Meetings" database
- Two-way completion sync via polling
- Notification service with channel abstraction; chat-feed channel implemented
- Three digests: morning plan (upgrades Phase 4's summary), meeting processed, evening wrap-up
- Digest generation as LLM job 5 (`LLM_MODEL_DIGEST`)

**Out:**
- Todoist, Slack, Email (future adapters if wanted)
- Team-facing follow-up messages
- At-risk/overdue push alerts (Phase 6)
- Real-time webhooks (polling is enough for single-user)

## Notion integration

**Setup:** internal Notion integration → token in `.env`; you share two databases with it (or the app creates them on first connect):
- **Tasks DB**: Title, Status (Open/Done/Dropped), Due, Priority, Category, Meeting (URL back to the app), AppTaskId (hidden key)
- **Meetings DB**: Title, Date, Status; page body = summary, decisions list, my tasks list

**Push (app → Notion):**
- Only tasks with `assignment = mine` sync (Notion mirrors *my* task list, not everyone's)
- On task create/update/complete/delete → upsert/archive the Notion page (queued, retried on API errors)
- On meeting extraction done → create/update its Meetings page

**Pull (Notion → app):**
- Poll the Tasks DB every `NOTION_POLL_MINUTES` (default 5) using `last_edited_time` filter
- Status changed in Notion → update `tasks.status` in-app (which also triggers a replan, freeing schedule blocks)
- Field edits (due date, priority) in Notion sync back too, marked `edited=true` so re-extraction respects them
- **Conflict rule**: most recent edit wins; ties go to the app. Every applied pull is logged to the sync log.

## Notification service

`services/notifier.py` — event in, formatted message out to every enabled channel.

```
event (morning_plan | meeting_processed | evening_wrapup)
      │
      ▼
[Digest generator]  LLM job 5, LLM_MODEL_DIGEST
      │   input: structured facts (blocks, tasks, counts) — already computed, never re-derived by the LLM
      │   output: short readable digest text (validated length/format)
      │   on LLM failure: fall back to a plain templated rendering — a digest must never fail to deliver
      ▼
[Channel dispatch]
      ├── chat feed (implemented now: assistant message in chat_messages)
      └── future adapters: slack, email — same interface, config-gated
```

**Digests:**

| Digest | Trigger | Content |
|--------|---------|---------|
| Morning plan | Phase 4 morning routine (08:00) | Today's blocks in order, first task highlighted, at-risk count, overdue count. Replaces Phase 4's hand-rolled summary with the channel-based service. |
| Meeting processed | Extraction + classification pipeline finishes | Meeting summary, my new tasks, maybe-mine count with a nudge to review the inbox. This is the personal "follow-up". |
| Evening wrap-up | New APScheduler job (`EVENING_WRAP_TIME`, default 19:30 — after work hours) | What got done today, what moved to tomorrow, tomorrow's first block. Weekdays only by default. |

## Database changes

```sql
-- notion mapping
ALTER TABLE tasks    ADD COLUMN notion_page_id TEXT;
ALTER TABLE meetings ADD COLUMN notion_page_id TEXT;

CREATE TABLE sync_log (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider   TEXT NOT NULL,              -- 'notion'
    direction  TEXT NOT NULL,              -- push | pull
    entity     TEXT NOT NULL,              -- task | meeting
    entity_id  UUID NOT NULL,
    action     TEXT NOT NULL,              -- created | updated | completed | archived | conflict
    detail     JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE notifications (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind       TEXT NOT NULL,              -- morning_plan | meeting_processed | evening_wrapup
    content    TEXT NOT NULL,
    channels   JSONB NOT NULL,             -- ["chat"] — which channels it went to
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`oauth_tokens` from Phase 4 is reused for the Notion token (`provider='notion'`, token in the encrypted column).

## Configuration (`backend/.env` additions)

```env
NOTION_TOKEN=secret_...            # internal integration token
NOTION_TASKS_DB_ID=...             # or blank → app creates DBs on connect
NOTION_MEETINGS_DB_ID=...
NOTION_POLL_MINUTES=5
LLM_MODEL_DIGEST=model-name-g      # LLM job 5: digest writing
EVENING_WRAP_TIME=19:30
NOTIFY_CHANNELS=chat               # comma-separated; future: chat,slack,email
```

## API changes

| Method | Path | Purpose |
|--------|------|---------|
| POST/DELETE | `/integrations/notion` | Connect (validate token, create/link DBs) / disconnect. |
| GET | `/integrations/notion/status` | Connection state, last push/pull times, pending queue size. |
| POST | `/integrations/notion/sync` | Manual full sync (push pending + pull now). |
| GET | `/sync-log` | Recent sync activity (debugging drift). |
| GET | `/notifications` | Digest history feed. |

## Frontend changes

- **`/settings/integrations` — new page**: Notion connect/disconnect, DB links, last-sync status, manual sync button, sync log viewer; notification toggles (which digests are on) and time settings
- **Dashboard**: latest morning digest pinned at the top of the Today column; Notion icon on tasks that are synced (links to the Notion page)
- **Chat**: digests render as distinct cards (not plain messages) with quick actions — "start first task", "open inbox"

## Build steps (in order)

1. **Notion client + connect flow**: token validation, DB create-or-link, settings UI
2. **Push sync**: task/meeting upsert on change (queued with retry), archive on delete; sync log
3. **Pull sync**: polling job, status/field write-back with conflict rule, replan trigger on completion
4. **Notification service**: channel abstraction, chat-feed adapter, notifications table + history endpoint
5. **Digest job (LLM job 5)**: prompt + validation + template fallback; migrate Phase 4's morning summary onto it
6. **Evening wrap-up**: APScheduler job, weekday gating
7. **Meeting-processed digest**: hook end of the extraction/classification pipeline
8. **End-to-end test**: complete a task in Notion → app marks it done, blocks free up, GCal updates; upload a meeting → digest card in chat + Notion page appears; morning and evening digests fire at configured times

## Definition of done

- [ ] My tasks (and only mine) appear in the Notion Tasks DB with status, due date, priority, and a link back to the app
- [ ] Each processed meeting gets a Notion page with summary, decisions, and my tasks
- [ ] Checking a task done in Notion marks it done in-app within one poll cycle, frees its schedule blocks, and updates GCal
- [ ] Conflicts resolve most-recent-wins and are visible in the sync log — no silent divergence
- [ ] Morning plan, meeting-processed, and evening wrap-up digests arrive in the chat feed at the right moments
- [ ] A digest still delivers (templated) when the LLM call fails
- [ ] Adding a future Slack/Email channel requires only a new adapter + `NOTIFY_CHANNELS` change
- [ ] Notion disconnect stops all sync without breaking local tasks
