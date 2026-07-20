# Data Model — Self Planner

> Consolidated data model for the entire project, merged from [Goal.md](Goal.md) and [phase1.md](phase1.md) … [phase6.md](phase6.md).
> Database: **PostgreSQL 16 + pgvector** (single database, single user: Anish). Audio binaries live in **MinIO** (S3-compatible); only their object keys are stored in the DB.

## Entity-Relationship overview

```
people                          oauth_tokens (provider PK)
  │ (resolved into)             availability_rules
  ▼                             busy_blocks
meetings ──1:N── segments       chat_messages
  │                             notifications
  ├──1:N── tasks ──1:N── schedule_blocks
  │           │
  │           └──(ref_id)── embeddings
  ├──1:N── embeddings
  └──(entity_id)── sync_log (also references tasks)
```

- **meetings** is the root aggregate: deleting a meeting cascades to its `segments`, `tasks`, and `embeddings`; deleting a task cascades to its `schedule_blocks`.
- **people** is a lookup registry; segments/tasks store canonical names (text), not FKs, so transcript data survives registry edits.
- Standalone tables (`availability_rules`, `busy_blocks`, `chat_messages`, `notifications`, `oauth_tokens`, `sync_log`) support planning, chat, and integrations.

## Entities

### meetings (Phase 1, extended in 2, 3, 5)

The central record for one uploaded recording and everything derived from it.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | `gen_random_uuid()` |
| title | TEXT NOT NULL | Defaults to filename without extension |
| filename | TEXT NOT NULL | Original upload name |
| audio_key | TEXT NOT NULL | MinIO object key (bucket `meetings-audio`) |
| duration_sec | REAL | |
| status | TEXT NOT NULL | `uploaded \| transcribing \| done \| failed` |
| error | TEXT | Transcription failure reason |
| summary | TEXT | LLM summary (Phase 2) |
| decisions | JSONB | `["Decision 1", …]` |
| extract_status | TEXT NOT NULL | `pending \| running \| done \| failed` |
| extract_error | TEXT | |
| diarize_status | TEXT NOT NULL | `pending \| running \| done \| failed \| skipped` (Phase 3) |
| speaker_map | JSONB NOT NULL `{}` | `{"SPEAKER_00": "Anish", …}` |
| notion_page_id | TEXT | Notion Meetings-DB page link (Phase 5) |
| created_at | TIMESTAMPTZ NOT NULL | |

### segments (Phase 1, extended in 3)

Timestamped transcript lines. Full transcript is always derived by joining segments — no duplicated `transcript` column to drift out of sync.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| meeting_id | UUID NOT NULL FK → meetings **ON DELETE CASCADE** | |
| idx | INT NOT NULL | Segment order |
| start_sec / end_sec | REAL NOT NULL | |
| text | TEXT NOT NULL | |
| speaker | TEXT | Canonical person name after mapping; NULL in Phase 1 |
| speaker_raw | TEXT | Raw pyannote label (`SPEAKER_00`), kept for re-mapping |

Index: `(meeting_id, idx)`.

### tasks (Phase 2, extended in 3, 4, 5, 6)

The richest entity — extraction output plus classification, planning, sync, and escalation state.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | **Stable across re-extracts** (reconcile, never delete-and-recreate) |
| meeting_id | UUID NOT NULL FK → meetings **ON DELETE CASCADE** | |
| title | TEXT NOT NULL | |
| owner | TEXT | Name as spoken; normalized to roster name in Phase 3 |
| due_date | DATE | Resolved to absolute date |
| priority | TEXT | `high \| medium \| low \| NULL` |
| dependencies | JSONB NOT NULL `[]` | |
| source_quote | TEXT | Traceability back to the transcript |
| status | TEXT NOT NULL | `open \| done \| dropped` |
| edited | BOOLEAN NOT NULL false | User edit guard — re-extract never overwrites |
| assignment | TEXT NOT NULL `'others'` | `mine \| maybe \| others` (Phase 3) |
| assignment_reason | TEXT | One-line LLM reasoning |
| assignment_source | TEXT NOT NULL `'llm'` | `llm \| user` — user decisions never overwritten |
| segment_idx | INT | Best-match segment for transcript highlighting |
| category | TEXT NOT NULL `'work'` | `work \| personal` (Phase 4) |
| estimated_minutes | INT | |
| estimate_source | TEXT NOT NULL `'llm'` | `llm \| user` — user overrides never re-estimated |
| steps | JSONB NOT NULL `[]` | Subtask steps for big tasks |
| progress | INT NOT NULL 0 | 0–100 (Gantt fill) |
| start_date | DATE | Gantt bar start |
| at_risk | BOOLEAN NOT NULL false | Deadline can't be met |
| notion_page_id | TEXT | Notion Tasks-DB page (Phase 5) |
| escalation_state | TEXT NOT NULL `'ok'` | `ok \| mentioned \| alerted \| resolved` (Phase 6) |
| escalated_at | TIMESTAMPTZ | |
| actual_minutes | INT | Rolled up from schedule block timestamps |
| created_at | TIMESTAMPTZ NOT NULL | |

Indexes: `(meeting_id)`, `(owner)`, `(assignment)`.

### people (Phase 3)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| name | TEXT NOT NULL **UNIQUE** | Canonical: "Anish" |
| aliases | JSONB NOT NULL `[]` | `["anish", "AB", …]` |
| is_me | BOOLEAN NOT NULL false | Exactly one row true (app-enforced invariant) |

### availability_rules (Phase 4)

Recurring weekly windows the scheduler may place blocks into.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| category | TEXT NOT NULL | `work \| personal` |
| weekday | INT NOT NULL | 0=Mon … 6=Sun |
| start_t / end_t | TIME NOT NULL | |

### busy_blocks (Phase 4)

Time the scheduler must avoid (timetables, manual entries).

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| label | TEXT NOT NULL | |
| weekday | INT | Recurring weekly if set |
| date | DATE | One-off if set — **exactly one of weekday/date** (CHECK-able invariant) |
| start_t / end_t | TIME NOT NULL | |
| source | TEXT NOT NULL `'manual'` | `manual \| timetable \| gcal` |

### schedule_blocks (Phase 4, extended in 6)

Concrete planned time slices of a task; mirrored to Google Calendar.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| task_id | UUID NOT NULL FK → tasks **ON DELETE CASCADE** | |
| start_at / end_at | TIMESTAMPTZ NOT NULL | |
| status | TEXT NOT NULL `'planned'` | `planned \| in_progress \| done \| skipped` |
| pinned | BOOLEAN NOT NULL false | User moved it in GCal; replans must not touch |
| gcal_event_id | TEXT | Link to the "Self Planner" calendar event |
| started_at / finished_at | TIMESTAMPTZ | Actual-time capture (Phase 6) |

### chat_messages (Phase 4)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| role | TEXT NOT NULL | `user \| assistant \| tool` |
| content | TEXT NOT NULL | |
| tool_calls | JSONB | |
| created_at | TIMESTAMPTZ NOT NULL | |

### oauth_tokens (Phase 4, reused in 5)

| Column | Type | Notes |
|--------|------|-------|
| provider | TEXT **PK** | `'google'`, `'notion'` |
| refresh_token | TEXT NOT NULL | **Encrypted at rest** (Fernet) |
| scopes | TEXT NOT NULL | |
| connected_at | TIMESTAMPTZ NOT NULL | |

### sync_log (Phase 5)

Append-only audit trail for external sync — every applied push/pull and conflict resolution is recorded.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| provider | TEXT NOT NULL | `'notion'` |
| direction | TEXT NOT NULL | `push \| pull` |
| entity | TEXT NOT NULL | `task \| meeting` |
| entity_id | UUID NOT NULL | |
| action | TEXT NOT NULL | `created \| updated \| completed \| archived \| conflict` |
| detail | JSONB | |
| created_at | TIMESTAMPTZ NOT NULL | |

### notifications (Phase 5)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| kind | TEXT NOT NULL | `morning_plan \| meeting_processed \| evening_wrapup` (+ weekly review, Phase 6) |
| content | TEXT NOT NULL | |
| channels | JSONB NOT NULL | `["chat"]` |
| created_at | TIMESTAMPTZ NOT NULL | |

### embeddings (Phase 6)

Requires `CREATE EXTENSION vector`.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| meeting_id | UUID NOT NULL FK → meetings **ON DELETE CASCADE** | |
| kind | TEXT NOT NULL | `segment \| summary \| decision \| task` |
| ref_id | UUID | segment/task id depending on kind |
| text | TEXT NOT NULL | |
| embedding | vector(1536) NOT NULL | Dim from `EMBED_DIM`; HNSW cosine index |

## Key relationships & lifecycle rules

1. **meeting → segments/tasks/embeddings**: `ON DELETE CASCADE` — deleting a meeting removes all derived data in one atomic statement; the MinIO object is deleted by the same request handler.
2. **task → schedule_blocks**: `ON DELETE CASCADE` — dropping a task frees its calendar slots (the GCal event cleanup follows via replan diffing).
3. **Names, not FKs, for speakers/owners**: `segments.speaker` and `tasks.owner` store canonical text from the `people` registry, resolved via `meetings.speaker_map`. This keeps historical transcripts immutable when the registry changes.
4. **User data is sticky**: `edited`, `assignment_source='user'`, `estimate_source='user'`, and `pinned` flags mark human decisions; every automated re-run (re-extract, re-classify, re-estimate, replan) must skip rows carrying them.
5. **Stable task identity**: re-extraction *reconciles* by fuzzy title match — updates in place, preserves `id`, `notion_page_id`, and user-sourced fields; never delete-and-recreate.
6. **External mirrors are linked, never duplicated**: `schedule_blocks.gcal_event_id` and `*.notion_page_id` are the join keys to the outside world; `sync_log` records every crossing of that boundary.

## ACID properties

The store is PostgreSQL, so every write already runs inside a transactional engine (WAL, MVCC). This section states what the *data model and application* must do so the guarantees actually hold end-to-end.

### Atomicity — all-or-nothing writes

- **Pipeline stage commits**: each stage (transcribe, diarize, extract, classify) writes its results and its status flag (`status`, `diarize_status`, `extract_status`) in **one transaction**. A meeting is never `done` with half its segments, and never has segments while stuck at `transcribing`.
- **Re-extract reconciliation** (update matched tasks + insert new + delete stale unedited ones) is a single transaction — a crash mid-reconcile can't leave a mixed task list.
- **Speaker-map save**: rewriting `segments.speaker` for all segments + updating `meetings.speaker_map` commits together; the transcript never shows a half-renamed speaker set.
- **Replan**: deleting future unpinned `schedule_blocks` and inserting the new plan is one transaction — there is never a moment with a partially built day.
- **Cascade deletes**: `DELETE FROM meetings WHERE id=…` atomically removes segments, tasks, embeddings, and (via task cascade) schedule blocks.
- **Cross-system boundary**: MinIO and external APIs (GCal, Notion) cannot join a Postgres transaction. Order of operations makes failures safe: upload audio *before* inserting the meeting row (an orphan object is harmless; a row without audio is not), and record external pushes in `sync_log` after commit so retries are idempotent via `gcal_event_id`/`notion_page_id` upserts.

### Consistency — every commit moves between valid states

- **Declarative constraints**: PKs on every table, `NOT NULL` on required fields, FKs with cascades, `UNIQUE(people.name)`, and defaults for every state column so a bare insert is already valid.
- **Enumerated states as CHECK constraints** (recommended at migration time): e.g. `status IN ('uploaded','transcribing','done','failed')`, `assignment IN ('mine','maybe','others')`, `progress BETWEEN 0 AND 100`, `end_sec >= start_sec`, `end_at > start_at`, and `busy_blocks`: `CHECK ((weekday IS NULL) <> (date IS NULL))`.
- **App-enforced invariants** (checked inside the same transaction that could break them): exactly one `people.is_me = true`; `speaker_map` values must exist in the registry; work blocks only inside work availability windows.
- **No derived-data drift by design**: transcript text lives only in segments; actual minutes roll up from block timestamps; stats are SQL aggregates — nothing is stored twice to disagree later.
- **Validation before write**: every LLM output passes Pydantic validation before any row is touched (design rule: structured output only), so invalid JSON can never reach the database.

### Isolation — concurrent work doesn't interleave badly

- Concurrency is real even single-user: background pipeline stages, APScheduler jobs (morning routine, evening wrap-up, Notion poll), chat tool calls, and UI edits can all run simultaneously.
- Postgres default `READ COMMITTED` + MVCC covers most access; the model adds:
  - **Row-level guards** for status transitions: `UPDATE meetings SET extract_status='running' WHERE id=… AND extract_status <> 'running'` — a re-extract click during an auto-run becomes a no-op instead of a double pipeline.
  - **`SELECT … FOR UPDATE`** on a task and its blocks during replan/escalation updates, so a Notion pull marking a task done and a replan touching its blocks serialize instead of clobbering each other.
  - **User-source flags as merge rules**: because `edited` / `assignment_source` / `estimate_source` / `pinned` are checked inside the writing transaction, an automated job can never overwrite a concurrent human decision — last-writer-wins is replaced by human-wins.
  - **Conflict rule for external edits** (Notion/GCal): most-recent-edit wins, ties go to the app, and the decision is committed together with a `sync_log` row so divergence is visible, never silent.

### Durability — committed means survives a crash

- Postgres WAL guarantees committed transactions survive process or machine crashes; Docker volumes (`pgdata`, `miniodata`) persist data across container restarts.
- **Status columns make every pipeline resumable**: after a crash, any meeting stuck in `transcribing`/`running` is detectable and retryable — the audio is still in MinIO precisely because failure handling never deletes it.
- **Append-only records** (`sync_log`, `notifications`, `chat_messages`) are the durable audit trail; they are inserted, never updated, so history can't be rewritten.
- **Secrets survive safely**: `oauth_tokens.refresh_token` is durable *and* encrypted at rest — durability never means plaintext credentials on disk.
- **Recovery-friendly external links**: because `gcal_event_id` and `notion_page_id` are committed with the entity, sync can always resume idempotently after a crash instead of creating duplicates.

## Full state-machine summary

| Column | States |
|--------|--------|
| meetings.status | uploaded → transcribing → done \| failed |
| meetings.extract_status | pending → running → done \| failed |
| meetings.diarize_status | pending → running → done \| failed \| skipped |
| tasks.status | open → done \| dropped |
| tasks.assignment | others / maybe / mine (maybe → mine via confirm, maybe → others via dismiss) |
| tasks.escalation_state | ok → mentioned → alerted → resolved (re-alert loop after 2 ignored days) |
| schedule_blocks.status | planned → in_progress → done \| skipped |

Every transition is committed atomically with the data it describes, which is what lets the UI poll a single `GET /meetings/{id}` and always see a coherent snapshot.
