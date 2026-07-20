# Phase 2 — Summary & Task Extraction

> Goal: after a meeting is transcribed, automatically generate a summary and extract structured tasks (with owners) via the LLM orchestrator.
> Parent doc: [Goal.md](Goal.md) · Builds on: [phase1.md](phase1.md)

## Decisions (locked)

| Decision | Choice | Notes |
|----------|--------|-------|
| LLM provider | **Custom base URL** (OpenAI-compatible) | Base URL, API key, and per-job model names all come from `.env`. |
| Trigger | **Auto after transcription + manual re-extract** | Pipeline runs on upload; "Re-extract" button re-runs it any time. |
| Task saving | **Auto-save, edit later** | Tasks go straight to the DB; UI supports edit/delete afterward. |
| Owner detection | **Transcript text only** | LLM infers owners from names spoken; `owner` is null when unclear. Speaker labels come in Phase 3. |

## Scope

**In:**
- LLM orchestrator: one client, per-job model routing via config
- Meeting summary generation (short summary + key decisions)
- Task extraction: title, owner, due date, priority, dependencies, source quote
- Auto-run after transcription; "Re-extract" button on the meeting page
- Tasks stored in Postgres; edit and delete from the UI
- Summary + task list shown on the meeting detail page

**Out (later phases):**
- Anish-only filtering (Phase 3) — Phase 2 extracts tasks for **everyone**
- Speaker labels / diarization (Phase 3)
- Planning, time estimation, scheduling (Phase 4)
- Follow-up message generation (later)

## Architecture

```
transcription done (Phase 1 pipeline)
      │
      ▼
[AI Orchestrator]  services/orchestrator.py
      │   one OpenAI-compatible client (base_url from .env)
      │   per-job model routing:
      ├── job: summary   → LLM_MODEL_SUMMARY
      └── job: extract   → LLM_MODEL_EXTRACT
      │
      ▼
raw LLM output (JSON mode / fenced JSON)
      │
      ▼
[Validation]  Pydantic schemas — retry once on invalid JSON
      │
      ▼
PostgreSQL: meetings.summary, tasks rows (replace-on-re-extract)
      │
      ▼
Next.js meeting page: summary card + task table (editable)
```

### Design rules applied (from Goal.md)

1. **Structured output only**: LLM returns JSON → Pydantic validation → DB rows. If validation fails, retry once with the error message appended; if it fails again, mark extraction `failed` and surface the error in the UI. Raw LLM text is never inserted directly.
2. **One model per job**: summary and extraction are separate calls with separate prompts and separately configurable models — even if they point at the same model initially.

## Configuration (`backend/.env` additions)

```env
LLM_BASE_URL=https://your-endpoint.example/v1
LLM_API_KEY=sk-...
LLM_MODEL_SUMMARY=model-name-a
LLM_MODEL_EXTRACT=model-name-b
LLM_TIMEOUT_SEC=120
```

The orchestrator uses the `openai` Python SDK with `base_url` override — works with any OpenAI-compatible endpoint.

## Database changes

```sql
-- meetings: extraction state + summary
ALTER TABLE meetings ADD COLUMN summary       TEXT;
ALTER TABLE meetings ADD COLUMN decisions     JSONB;          -- ["Decision 1", ...]
ALTER TABLE meetings ADD COLUMN extract_status TEXT NOT NULL DEFAULT 'pending';
                     -- pending | running | done | failed
ALTER TABLE meetings ADD COLUMN extract_error  TEXT;

CREATE TABLE tasks (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id   UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    owner        TEXT,                     -- name as spoken; NULL if unclear
    due_date     DATE,                     -- resolved to absolute date; NULL if none
    priority     TEXT,                     -- high | medium | low | NULL
    dependencies JSONB NOT NULL DEFAULT '[]',   -- ["Backend API ready", ...]
    source_quote TEXT,                     -- transcript line that produced this task
    status       TEXT NOT NULL DEFAULT 'open',  -- open | done | dropped
    edited       BOOLEAN NOT NULL DEFAULT false, -- true once user modifies it
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tasks_meeting ON tasks (meeting_id);
CREATE INDEX idx_tasks_owner   ON tasks (owner);
```

Notes:
- `source_quote` makes every task traceable to the transcript — key for debugging bad extractions.
- `edited` protects your manual fixes: **re-extract replaces only unedited tasks** and leaves edited ones untouched.
- `owner` is free text in Phase 2; Phase 3 normalizes it ("Anish", "anish", "him" → canonical person).

## Extraction pipeline

`services/extraction.py` — orchestrates the two jobs:

1. Set `extract_status=running`
2. Build transcript text from segments (with timestamps, so due-date context like "by Friday" can be resolved against `meetings.created_at`)
3. **Job 1 — summary**: prompt → `{summary: str, decisions: [str]}` → validate → save
4. **Job 2 — extract**: prompt → `{tasks: [...]}` → validate (Pydantic) → **reconcile** with existing tasks for this meeting: match by fuzzy title; matched tasks are updated in place (preserving their id and any user-sourced data — `edited`, and later phases' `assignment_source='user'` and `notion_page_id`); unmatched old tasks are deleted only if they carry no user-sourced data; new ones inserted. Never delete-and-recreate — task ids must be stable across re-extracts.
5. Set `extract_status=done` (or `failed` + `extract_error`)

Each job is independent: a summary failure doesn't block task extraction and vice versa (run both, collect errors).

### Long transcripts

If the transcript exceeds the model's context comfort zone (~12k words as a starting threshold), chunk by segments with overlap, extract per chunk, and merge task lists (dedupe by near-identical titles). Summary uses map-reduce: summarize chunks, then summarize the summaries. Keep this behind a simple `if` — most meetings won't need it.

### Prompts (versioned in code, `prompts/` module)

**Summary prompt** — input: transcript; output JSON: `{"summary": "...", "decisions": ["..."]}`. Instructions: 3–6 sentence neutral summary, decisions are explicit agreements only.

**Extraction prompt** — input: transcript + meeting date; output JSON:

```json
{
  "tasks": [
    {
      "title": "Integrate authentication",
      "owner": "Anish",
      "due_date": "2026-07-14",
      "priority": "high",
      "dependencies": ["Backend API ready"],
      "source_quote": "Anish will integrate authentication once the API is ready Friday."
    }
  ]
}
```

Key instructions:
- Extract **all** tasks for **all** people (filtering is Phase 3's job)
- Owners only when a name is stated or clearly implied; otherwise `null` — never guess
- Resolve relative dates ("Friday", "next week") against the meeting date; `null` if no deadline mentioned
- `source_quote` must be a near-verbatim transcript line
- Priority only when urgency is expressed; otherwise `null`

## API changes

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/meetings/{id}/extract` | Re-run summary + extraction. Returns updated meeting + tasks. Reconciles with existing tasks (stable ids, user data preserved). |
| GET | `/meetings/{id}/tasks` | Tasks for one meeting. |
| GET | `/tasks` | All tasks across meetings (query params: `owner`, `status`). |
| PATCH | `/tasks/{id}` | Edit any field (title, owner, due_date, priority, status). Sets `edited=true`. |
| DELETE | `/tasks/{id}` | Remove a task. |

`GET /meetings/{id}` response grows: `summary`, `decisions`, `extract_status`, `extract_error`, `tasks[]`.

Phase 1's upload endpoint changes: after transcription succeeds, it calls the extraction pipeline before returning (still synchronous, same timeout posture as Phase 1).

## Frontend changes

### `/meetings/[id]` — additions
- **Summary card**: summary text + "Key decisions" bullet list; skeleton/spinner while `extract_status=running`
- **Tasks table**: title, owner, due date, priority, status — inline editable (click to edit, PATCH on blur), delete per row
- **Re-extract button**: confirm dialog noting that unedited tasks will be replaced; disabled while running
- If `extract_status=failed`: error banner with the message and the Re-extract button as retry

### `/tasks` — new page
- All tasks across all meetings in one table
- Filter by owner and status
- Each row links back to its meeting (and `source_quote` shown on hover/expand)

## Build steps (in order)

1. **Config + client**: `.env` additions, orchestrator module with OpenAI-compatible client and per-job model lookup
2. **DB migration**: meetings columns + tasks table
3. **Prompts + schemas**: prompt templates, Pydantic response models, JSON parse-and-retry helper
4. **Extraction pipeline**: summary job + extraction job + replace-unedited-tasks logic
5. **Wire into upload flow**: run pipeline after transcription; add `POST /meetings/{id}/extract`
6. **Task endpoints**: GET/PATCH/DELETE tasks
7. **Frontend meeting page**: summary card, tasks table with inline edit, re-extract button
8. **Frontend tasks page**: cross-meeting task list with filters
9. **End-to-end test**: upload a real meeting → transcript → summary + tasks appear; edit a task, re-extract, confirm the edited task survives

## Definition of done

- [ ] Uploading a meeting produces transcript **and** summary + tasks with no extra clicks
- [ ] Tasks have title, owner (or null), due date resolved to a real date, priority, and a source quote
- [ ] Invalid LLM JSON is retried once, then surfaces as `failed` with a visible error — never a crash, never garbage rows
- [ ] Re-extract keeps task ids stable and preserves all user-sourced data (edits, and in later phases inbox decisions and Notion links)
- [ ] Tasks are editable and deletable from the UI
- [ ] `/tasks` page lists all tasks filterable by owner
- [ ] Swapping models per job requires only an `.env` change
