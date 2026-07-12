# Phase 4 — Daily Planner, Calendar, Gantt & Chatbot

> Goal: turn my tasks into a realistic schedule that respects my real availability and existing calendar, track multi-day work on a Gantt chart, and manage it all through a chatbot that can also ingest a timetable and sync everything to Google Calendar.
> Parent doc: [Goal.md](Goal.md) · Builds on: [phase1.md](phase1.md), [phase2.md](phase2.md), [phase3.md](phase3.md)

## Decisions (locked)

| Decision | Choice | Notes |
|----------|--------|-------|
| Availability | **Work tasks in office hours, personal on weekends** | Work: Mon–Fri 10:00–19:00. Personal: weekend afternoons only — weekday evenings stay completely free. Tasks get a `category` (work/personal). |
| Google Calendar | **Read + write, two-way** | Read existing events so the planner never double-books; push planned blocks as events; manual changes to Self Planner events in GCal sync back into the app. OAuth2. Pulled forward from Phase 5. |
| Pacing | **25–90 min blocks, 10-min buffers, 4h deep work/day** | Overflow spills to the next day. |
| Morning routine | **Auto-replan + chat summary** | Scheduled job each morning: pull GCal, replan the day, post a "here's your day" summary in chat. |
| Timetable upload | **Image, PDF, CSV/Excel, plain text** | All formats parsed to busy blocks; images via a vision-capable model on the base URL. |
| Gantt | **Tasks across days/weeks with dependencies** | Bars from start→due date, dependency arrows, progress fill, today-line. |

### Scope note

This phase is large. It's built in three sub-milestones, each independently shippable:
- **4a — Planner core**: availability model, time estimation, scheduler, day plan view
- **4b — Google Calendar + timetable**: OAuth, read/write sync, timetable ingestion
- **4c — Gantt + chatbot**: tracking view, conversational interface

## Availability model

Three layers, combined at scheduling time. Free slots = availability windows − busy blocks − GCal events − already-scheduled blocks.

```
Layer 1: recurring availability rules (editable in settings)
  work window:      Mon–Fri 10:00–19:00
  personal windows: Sat–Sun 12:00–18:00   (weekday evenings deliberately free; editable)

Layer 2: busy blocks (from uploaded timetables + manual entries)
  e.g. "Gym Mon/Wed 20:00–21:00", "Standup daily 10:15–10:30"

Layer 3: Google Calendar events (synced, read-only in our DB)
  real meetings block scheduling in whatever window they fall
```

Placement rules:
- `category=work` tasks → only in the work window
- `category=personal` tasks → only in weekend-afternoon windows
- Weekday evenings are **never scheduled** — they don't exist as availability
- Meetings uploaded from the office default their tasks to `work`; the chatbot asks when a task's category is unclear
- Weekend afternoons take personal tasks by default, and work tasks **only** when a deadline can't be met otherwise (scheduler flags this as an "overflow warning" instead of silently using your weekend)

## Planner engine

`services/planner.py` — deterministic scheduler; the LLM only estimates, never places blocks (design rule 1: structure over vibes).

Pipeline:
1. **Estimate** (LLM job 4, `LLM_MODEL_PLAN`): for each unestimated task → `{estimated_minutes, steps[]}`; big tasks (> 2h) get split into subtask steps. User can override any estimate; overrides are never re-estimated.
2. **Order**: topological sort by dependencies, then priority, then due date.
3. **Place**: greedy earliest-fit into free slots of the matching category. Chunks work into 25–90 min blocks, inserts 10-min buffers between blocks, max 4h of deep work per day before spillover to the next day.
4. **Verify**: any task that can't finish before its due date → `at_risk` flag + overflow suggestions (use weekend, extend hours, renegotiate deadline) surfaced in UI/chatbot — never silently dropped.

Replanning runs on: new tasks classified `mine`, task edits, estimate overrides, calendar changes, timetable upload, an explicit "replan" (button/chat), or the morning routine. Completed, in-progress, and pinned blocks are never moved; only future unpinned blocks reshuffle.

### Morning routine

A scheduled job (APScheduler in the FastAPI process; time configurable via `MORNING_PLAN_TIME`, default 08:00) runs daily:
1. Pull fresh GCal events (including two-way drift detection)
2. Replan the day
3. Post a **"here's your day" summary** as an assistant message in chat: today's blocks in order, at-risk items, overdue tasks — the foundation for Phase 5 notifications

## Google Calendar integration

- **Auth**: Google OAuth2 (offline access, refresh token stored encrypted). One-time consent screen; `GOOGLE_CLIENT_ID/SECRET` in `.env`. Settings page shows connect/disconnect.
- **Read**: sync events for the next 14 days (poll on plan/replan + manual refresh button). Events become read-only busy entries.
- **Write**: each planned block → a GCal event in a dedicated **"Self Planner" calendar** (created on first sync). Using a separate calendar means we can safely update/delete our own events on replan without ever touching real meetings, and you can toggle its visibility in GCal.
- **Sync mapping**: `schedule_blocks.gcal_event_id` links blocks to events; replan diffs blocks and patches/creates/deletes events accordingly.
- **Two-way sync**: on every sync, Self Planner events are compared against their blocks. If you **moved** an event in GCal, the block is rescheduled to match (marked `pinned` so replans don't move it back); if you **deleted** an event, the block is marked `skipped`. The calendar is a real control surface, not just a display.

## Timetable ingestion

Chat upload (or settings page upload) → parsed to recurring busy blocks → shown as a **preview table for confirmation** before saving (LLM parsing of images/PDFs is fallible; never write busy blocks unconfirmed).

| Format | Path |
|--------|------|
| Image/screenshot | vision model (`LLM_MODEL_VISION`) → structured JSON |
| PDF | text extraction (pypdf) → LLM parse; fall back to vision on scanned PDFs |
| CSV/Excel | pandas parse (day/start/end/activity columns; LLM maps unfamiliar headers) |
| Plain text in chat | LLM parse directly from the message |

Target JSON per entry: `{day: "mon", start: "20:00", end: "21:00", label: "Gym", weekly: true}`.

## Chatbot

Chat panel available on every page (slide-over) + full page at `/chat`. Tool-calling agent on `LLM_MODEL_CHAT` with conversation history stored in DB.

**Tools:**

| Tool | Does |
|------|------|
| `add_task` | Create a task from chat ("remind me to review Rahul's PR by Thursday") |
| `update_task` / `complete_task` | Edit, mark done, change progress |
| `query` | Answer "what's my day look like?", "what's overdue?", "when am I free Friday?" |
| `replan` | Trigger the planner engine |
| `parse_timetable` | Handle uploaded timetable files (routes to ingestion above) |
| `set_availability` | Adjust availability rules ("I'm off next Friday", "extend work hours today") |

**Clarification behavior** (your requirement): before calling `add_task`, the bot must have title + category (work/personal) + a due date or explicitly none. If anything is missing or ambiguous it asks **one** concise question rather than guessing — e.g. "Is reviewing Rahul's PR an office task, and by when?" Same JSON-validation discipline as every other LLM job: tool arguments are Pydantic-validated before execution.

## Database changes

```sql
CREATE TABLE availability_rules (
    id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category TEXT NOT NULL,               -- work | personal
    weekday  INT  NOT NULL,               -- 0=Mon … 6=Sun
    start_t  TIME NOT NULL,
    end_t    TIME NOT NULL
);

CREATE TABLE busy_blocks (
    id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label    TEXT NOT NULL,
    weekday  INT,                          -- recurring weekly if set
    date     DATE,                         -- one-off if set (exactly one of weekday/date)
    start_t  TIME NOT NULL,
    end_t    TIME NOT NULL,
    source   TEXT NOT NULL DEFAULT 'manual'  -- manual | timetable | gcal
);

CREATE TABLE schedule_blocks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    start_at      TIMESTAMPTZ NOT NULL,
    end_at        TIMESTAMPTZ NOT NULL,
    status        TEXT NOT NULL DEFAULT 'planned',  -- planned | in_progress | done | skipped
    pinned        BOOLEAN NOT NULL DEFAULT false,   -- user moved it in GCal; replans must not touch it
    gcal_event_id TEXT
);

CREATE TABLE chat_messages (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role       TEXT NOT NULL,              -- user | assistant | tool
    content    TEXT NOT NULL,
    tool_calls JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- tasks: planning fields
ALTER TABLE tasks ADD COLUMN category          TEXT NOT NULL DEFAULT 'work';  -- work | personal
ALTER TABLE tasks ADD COLUMN estimated_minutes INT;
ALTER TABLE tasks ADD COLUMN estimate_source   TEXT NOT NULL DEFAULT 'llm';   -- llm | user
ALTER TABLE tasks ADD COLUMN steps             JSONB NOT NULL DEFAULT '[]';
ALTER TABLE tasks ADD COLUMN progress          INT  NOT NULL DEFAULT 0;       -- 0–100
ALTER TABLE tasks ADD COLUMN start_date        DATE;                          -- Gantt bar start
ALTER TABLE tasks ADD COLUMN at_risk           BOOLEAN NOT NULL DEFAULT false;

-- google tokens (single user)
CREATE TABLE oauth_tokens (
    provider      TEXT PRIMARY KEY,        -- 'google'
    refresh_token TEXT NOT NULL,           -- encrypted at rest
    scopes        TEXT NOT NULL,
    connected_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Configuration (`backend/.env` additions)

```env
LLM_MODEL_PLAN=model-name-d      # estimation job
LLM_MODEL_CHAT=model-name-e      # chatbot agent
LLM_MODEL_VISION=model-name-f    # timetable image parsing
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
TOKEN_ENCRYPTION_KEY=...         # Fernet key for refresh token at rest
TIMEZONE=Asia/Kolkata
MORNING_PLAN_TIME=08:00          # daily auto-replan + chat summary
```

## API changes

| Method | Path | Purpose |
|--------|------|---------|
| GET/PUT | `/availability` | Read/update availability rules. |
| GET/POST/DELETE | `/busy-blocks` | Manage busy blocks. |
| POST | `/timetable/parse` | Upload timetable file → parsed preview (not saved). |
| POST | `/timetable/confirm` | Save confirmed busy blocks. |
| POST | `/plan` | Run/re-run the planner. Returns schedule + at-risk warnings. |
| GET | `/plan/today` · `/plan/range?from&to` | Day plan / Gantt data (tasks + blocks + dependencies). |
| PATCH | `/schedule-blocks/{id}` | Mark in-progress/done/skipped; manual drag-reschedule. |
| GET | `/auth/google` · `/auth/google/callback` · DELETE `/auth/google` | OAuth connect/disconnect. |
| POST | `/gcal/sync` | Manual pull of calendar events + push of pending blocks. |
| POST | `/chat` | Chat message in, agent reply out (streaming); handles file attachments. |

## Frontend changes

- **`/` dashboard additions**: "Today" column — the day's schedule blocks in order, with done/skip buttons and at-risk warnings
- **`/gantt` — new page**: tasks as bars (`start_date` → `due_date`), progress fill from `progress`, dependency arrows, today-line, red outline on `at_risk`; week/month zoom; click bar → task detail. Library: `frappe-gantt` (lightweight) unless we outgrow it.
- **`/chat` — new page + global slide-over**: streaming chat, file-drop for timetables, tool-call results rendered as cards (task created, plan updated, busy blocks preview with Confirm button)
- **`/settings/availability` — new page**: weekly grid editor for availability rules + busy blocks list; Google Calendar connect/disconnect + sync status

## Build steps (in order)

**4a — Planner core**
1. Availability rules + busy blocks: tables, CRUD, settings grid UI; seed your defaults (Mon–Fri 10:00–19:00 work, Sat–Sun 12:00–18:00 personal — no weekday evenings)
2. Task planning fields migration; estimation job (LLM job 4) with user-override protection
3. Planner engine: ordering, slot computation, placement, buffers, at-risk detection; unit-test with fixed fixtures (no LLM in scheduler tests)
4. Day plan on dashboard + `/plan` endpoints; block status updates

**4b — Calendar + timetable**
5. Google OAuth flow + encrypted token storage + settings UI
6. GCal read (events → busy), write (blocks → "Self Planner" calendar), replan diffing, two-way drift sync (moved → pinned reschedule, deleted → skipped)
7. Timetable ingestion: parse endpoints for all four formats + confirm-preview flow

**4c — Gantt + chatbot**
8. Gantt page with dependencies, progress, today-line
9. Chat agent: tool definitions, clarification loop, history persistence, streaming endpoint
10. Chat UI (page + slide-over) with file upload wired to timetable ingestion
11. Morning routine: APScheduler job → GCal pull → replan → summary message in chat
12. **End-to-end test**: meeting upload → my tasks → estimates → schedule appears in day plan, Gantt, and Google Calendar; chatbot adds a task with one clarifying question and it lands in all three views

## Definition of done

- [ ] Work tasks are only ever scheduled Mon–Fri 10:00–19:00; personal tasks only in weekend afternoons; weekday evenings are never scheduled
- [ ] Weekend work-overflow requires an explicit warning acknowledgment — never silent
- [ ] Existing Google Calendar events are never double-booked; planned blocks appear in a separate "Self Planner" calendar and update cleanly on replan
- [ ] Moving a Self Planner event in GCal reschedules (and pins) its block; deleting one marks the block skipped
- [ ] Every morning at the configured time, the day is replanned and a summary appears in chat
- [ ] A photo, PDF, CSV, or pasted text of a timetable becomes confirmed busy blocks via preview
- [ ] Gantt shows every task as a bar with dependencies, progress, and at-risk highlighting
- [ ] Undeliverable deadlines are flagged `at_risk` with suggestions — never silently dropped
- [ ] Chatbot can add/update/complete tasks, answer schedule questions, ingest timetables, and trigger replans — asking exactly one clarifying question when details are missing
- [ ] Completed/in-progress blocks never move during replans; user estimate overrides are never re-estimated
