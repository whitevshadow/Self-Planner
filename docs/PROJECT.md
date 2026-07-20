# Self Planner — Project Overview

> **AI-powered personal meeting assistant.** It listens to a meeting, extracts the action items that belong to **Anish**, and turns them into a realistic, availability-aware daily plan.

- **Status:** Phase 4 complete (Google Calendar sync deliberately skipped). Phases 5–6 planned, not built.
- **Type:** Single-user web app (backend API + Next.js dashboard + Docker infra).
- **Last documented:** 2026-07-20

---

## 1. What the system does

After a meeting, action items are scattered across memory, chat, and notes — tasks assigned to you get lost and planning the day is manual. Self Planner automates the whole chain:

```
Upload audio
  → transcribe (speech-to-text)
  → diarize / label speakers
  → LLM extracts tasks, decisions, summary, meeting minutes
  → classify each task: mine | maybe-mine | others
  → triage (priority + duration estimate + start/due date)
  → deterministic planner schedules "mine" tasks into free time
  → Gantt + Today views; chatbot manages everything
```

**Core design rule — structured output only:** the LLM never writes tasks directly into the list. The flow is always `transcript → structured JSON → validation → task creation → plan generation`. Each job (cleanup, extraction, classification, triage, planning, chat) uses its own prompt and can use its own model.

---

## 2. Current status by phase

| Phase | Scope | Status |
|-------|-------|--------|
| **1 — Meeting → transcript** | Upload audio, transcribe, show transcript in UI | ✅ Done |
| **2 — Summary & task extraction** | Summary, decisions, meeting notes, task extraction with owner detection | ✅ Done |
| **3 — Anish-only filter** | Speaker diarization, people registry, 3-bucket classification (mine/maybe/others) | ✅ Done |
| **4 — Daily planner** | Availability-aware scheduling, timetable ingestion, Gantt chart, planning chatbot, morning auto-replan | ✅ Done (Google Calendar **skipped by decision**) |
| **5 — Notion sync & notifications** | Two-way Notion task sync, meeting pages, digest notifications | ⬜ Planned ([phase5.md](phase5.md)) |
| **6 — Smart assistant** | pgvector meeting memory, escalating overdue warnings, "what next", estimate learning, weekly review | ⬜ Planned ([phase6.md](phase6.md)) |

**Open TODO:** transcript/chat full-text or pgvector search wired into the ⌘K dropdown (deferred from the 2026-07-13 redesign — see [TODOS.md](TODOS.md)).

---

## 3. Architecture

```
┌─────────────┐   HTTP    ┌──────────────────────────┐
│  Next.js UI │ ────────▶ │  FastAPI backend (:8000) │
│   (:3000)   │ ◀──────── │                          │
└─────────────┘  polling  │  routers → services      │
                          └────────────┬─────────────┘
                                       │
        ┌──────────────┬───────────────┼──────────────┬───────────────┐
        ▼              ▼               ▼              ▼               ▼
   PostgreSQL 16    MinIO         faster-whisper   pyannote     LLM gateway
   (pgvector)      (audio S3)       (local STT)   (diarize)   (OpenAI-compat
   :5432          :9000/:9001                                  LiteLLM :1050)
```

- **Backend** — FastAPI + SQLAlchemy 2.0. A 202-immediate upload kicks off a background pipeline; the UI polls per-stage status columns.
- **Frontend** — Next.js 15 App Router, React 19, `frappe-gantt` for the timeline, `react-markdown` for notes.
- **Infra** — PostgreSQL 16 (`pgvector/pgvector:pg16`) + MinIO, both via `docker-compose.yml`.
- **STT** — `faster-whisper` running locally on CPU (`small` model, int8). Can switch to a gateway `/v1/audio/transcriptions` endpoint via `ASR_PROVIDER=gateway`.
- **LLM** — any OpenAI-compatible endpoint (a LiteLLM gateway). Per-job model routing via `.env`.

---

## 4. Backend

Location: [backend/app/](backend/app/)

### Routers (API surface — base `http://localhost:8000/api`)

| Router | Responsibility |
|--------|----------------|
| `meetings.py` | Upload, list, detail, delete, re-transcribe, extract, classify, speaker mapping |
| `tasks.py` | List/edit/delete tasks, confirm/dismiss maybe-mine, bulk assign-mine |
| `people.py` | People registry CRUD (names, aliases, `is_me`) |
| `planner.py` | Availability rules, busy blocks, plan generation, today/range views, schedule-block edits |
| `chat.py` | Chatbot conversation + timetable parse/confirm |

### Services (the working logic)

| Service | Role |
|---------|------|
| `pipeline.py` | Orchestrates the background flow: **transcribe → diarize → extract → classify**; reclaims orphaned rows after a restart |
| `transcriber.py` | Speech-to-text (the only place transcription is touched) |
| `diarizer.py` | pyannote.audio wrapper — aligns speaker turns onto Whisper segments |
| `extraction.py` | LLM jobs 1 & 2 — summary + task extraction |
| `classifier.py` | LLM job 3 — every task → mine / maybe / others |
| `triage.py` | LLM job 6 — priority + duration estimate + start/due dates |
| `planner.py` | **Deterministic** scheduler — packs tasks into availability windows |
| `chat_agent.py` | Chatbot agent with a JSON tool-call protocol |
| `timetable.py` | Ingest image / PDF / CSV-Excel / text → confirmed busy blocks |
| `orchestrator.py` | Single OpenAI-compatible client with per-job model routing |
| `prompts.py` | Versioned prompt templates |
| `model_discovery.py` | Discovers available gateway models |
| `scheduler_jobs.py` | APScheduler — morning auto-replan + chat summary at 08:00 |
| `storage.py` | MinIO upload/download/delete |

### Data model (PostgreSQL)

| Table | Purpose |
|-------|---------|
| `meetings` | Audio metadata, status columns (`status`, `diarize_status`, `extract_status`), summary, decisions, notes, `speaker_map` |
| `segments` | Timestamped transcript lines with `speaker` (canonical) + `speaker_raw` (pyannote label) |
| `tasks` | Extracted tasks: owner, due/start date, priority, `assignment` (mine/maybe/others), category, `estimated_minutes`, steps, progress, `edited` flag |
| `availability_rules` | Weekly work/personal windows (weekday + start/end time) |
| `busy_blocks` | Recurring or one-off busy times (from timetables) |
| `schedule_blocks` | Planned task blocks (`start_at`/`end_at`, `pinned`, `gcal_event_id`) |
| `chat_messages` | Chatbot history with tool calls |
| `people` | People registry (name, aliases, `is_me`) |

Full schema notes live in [datamodel.md](datamodel.md).

### Key behaviors

- **Upload returns 202 immediately;** the pipeline runs in the background and the UI polls per-stage status.
- **Audio is uploaded to MinIO before the DB row is inserted,** and kept on failure so retries work.
- **Edited tasks are protected** — `edited=true` and confirm/dismiss decisions are sticky and never overwritten by re-extraction.
- **Diarization needs `HF_TOKEN`** (+ accepting pyannote terms on Hugging Face); without it the pipeline skips diarization and the UI offers manual speaker labels.

---

## 5. Planner rules (Phase 4)

Deterministic scheduling — the LLM only *estimates*; the planner *places*:

- **Work availability:** Mon–Fri 10:00–19:00 (weekday evenings deliberately empty).
- **Personal availability:** Sat–Sun 12:00–18:00.
- **Blocks:** 25–90 min each, **10-min buffers** between them.
- **Deep-work cap:** 4 h (240 min) per day.
- **Horizon:** 14 days.
- Busy blocks from ingested timetables are treated as unavailable.
- Morning auto-replan + chat summary fires at **08:00** (`Asia/Kolkata`).

---

## 6. Frontend

Location: [frontend/src/](frontend/src/)

| Route | Page |
|-------|------|
| `/` | Dashboard (today's plan, recent meetings, upload) |
| `/meetings` · `/meetings/[id]` | Meeting list & detail (transcript, summary, notes, tasks, speaker map) |
| `/tasks` | All tasks across meetings |
| `/gantt` | Gantt timeline of scheduled blocks |
| `/chat` | Planning chatbot + timetable ingestion |
| `/settings/people` · `/settings/availability` | People registry & availability rules |

Notable components: `Shell` / `Sidebar` / `TopBar` (layout), `UploadForm` / `RecordButton`, `TranscriptView`, `SummaryCard`, `MeetingNotes`, `TaskTable`, `TodayColumn`, `MiniCalendar`, `SpeakerMapBar`. Design source of truth: [frontend/DESIGN.md](frontend/DESIGN.md) (glassy redesign — see [redesign-plan.md](redesign-plan.md)).

---

## 7. LLM jobs & model routing

One model per job, configured in `.env`. Each falls back to `LLM_MODEL_EXTRACT` if unset.

| Job | Env var | Default / note |
|-----|---------|----------------|
| Summary | `LLM_MODEL_SUMMARY` | — |
| Extraction | `LLM_MODEL_EXTRACT` | base fallback for others |
| Classification | `LLM_MODEL_CLASSIFY` | mine/maybe/others |
| Triage | `LLM_MODEL_TRIAGE` | `gpt-oss-120b` (reasoning-heavy: date math + effort sizing) |
| Planning/estimate | `LLM_MODEL_PLAN` | falls back to extract |
| Chat | `LLM_MODEL_CHAT` | falls back to extract |
| Vision (timetables) | `LLM_MODEL_VISION` | `meta/llama-3.2-90b-vision-instruct` |

Gateway base URL via `LLM_BASE_URL` (`base_URL` legacy alias), key via `LLM_API_KEY` (`OPENAI_API_KEY` legacy alias). `LLM_REASONING_EFFORT` defaults to `none` (the param is omitted unless set to low/medium/high — some gateways hang on invalid values).

---

## 8. Running it

**Prerequisites:** Docker Desktop, Python 3.13+, Node 20+, ffmpeg on PATH.

```powershell
# 1. Infra — Postgres :5432, MinIO :9000/:9001
docker compose up -d

# 2. Backend — http://localhost:8000 (docs at /docs)
cd backend
python -m venv .venv                                 # first time only
.\.venv\Scripts\pip install -r requirements.txt      # first time only
.\.venv\Scripts\uvicorn app.main:app --port 8000 --timeout-keep-alive 600

# 3. Frontend — http://localhost:3000
cd frontend
npm install                                          # first time only
npm run dev
```

Open http://localhost:3000, upload an `.mp3`/`.wav`/`.m4a`, and wait for the transcript. **First upload downloads the Whisper model (~460 MB)**; later uploads are faster. Config lives in the root `.env`.

The whole stack can also run via Docker Compose (`db`, `minio`, `backend`, `frontend`); the backend joins the external `litellm_default` network to reach the LLM gateway as `app:1050` and is configured for optional NVIDIA GPU access.

---

## 9. Key API endpoints

Base: `http://localhost:8000/api`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/meetings` | Upload audio (multipart `file`, optional `title`) — **202**, pipeline runs in background |
| GET | `/meetings` · `/meetings/{id}` | List / detail with segments |
| DELETE | `/meetings/{id}` | Delete meeting + segments + tasks + audio |
| POST | `/meetings/{id}/extract` · `/classify` · `/retranscribe` | Re-run stages (edited tasks preserved) |
| PUT | `/meetings/{id}/speaker-map` | Map raw speaker labels to people, re-run classification |
| GET/PATCH/DELETE | `/tasks` · `/tasks/{id}` | List / edit (sets `edited=true`) / delete |
| POST | `/tasks/{id}/confirm` · `/dismiss` · `/assign-mine` | Maybe-mine inbox decisions |
| GET/PUT | `/planner/availability` | Availability rules |
| GET/POST/DELETE | `/planner/busy-blocks` | Busy blocks |
| POST | `/planner/plan` | Generate the plan |
| GET | `/planner/plan/today` · `/plan/range` | Read the schedule |
| PATCH | `/planner/schedule-blocks/{id}` | Move / pin a block |
| GET/POST | `/chat` | Chatbot conversation |
| POST | `/timetable/parse` · `/confirm` | Timetable ingestion (image/PDF/CSV/text → busy blocks) |
| GET/POST/PATCH/DELETE | `/people` | People registry |

---

## 10. Reference docs in this repo

- [Goal.md](Goal.md) — full vision, system layers, design rules
- [phase1.md](phase1.md)–[phase6.md](phase6.md) — per-phase build plans
- [datamodel.md](datamodel.md) — data model details
- [redesign-plan.md](redesign-plan.md) / [frontend/DESIGN.md](frontend/DESIGN.md) — glassy UI redesign
- [README.md](README.md) — quick start
- [TODOS.md](TODOS.md) — deferred work
- `gateway-models.txt` — available gateway model list

---

## 11. Out of scope (for now)

Real-time in-meeting suggestions · multi-user / team accounts · mobile app · automatic voice recognition (manual labels for MVP) · Google Calendar sync (skipped in Phase 4).
