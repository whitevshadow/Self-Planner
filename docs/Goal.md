# Goal — Self Planner

An AI-powered personal meeting assistant that listens to meetings, extracts the tasks that belong to **Anish**, and automatically turns them into a realistic daily plan synced to the tools I already use.

## Problem

After a meeting, action items are scattered across memory, chat, and notes. Tasks assigned to me get lost, deadlines slip, and planning the day is manual work.

## What the system does

1. Record or upload a meeting (audio file or live capture).
2. Convert audio to text (speech-to-text).
3. Identify who said what (speaker diarization / manual labels for MVP).
4. Extract tasks, deadlines, priorities, and decisions using LLMs.
5. Filter to keep **only tasks assigned to Anish** — including indirect assignments ("Can Anish check this?").
6. Generate a realistic daily plan with time estimates, buffers, and breaks.
7. Push tasks and plans to external tools (Google Calendar, Notion, Todoist, Slack/Email).
8. Remember everything — transcripts, tasks, plans, and history — across meetings.

## Success criteria

- Upload a meeting recording → get a clean transcript within minutes.
- Zero tasks assigned to me are missed, including indirectly phrased ones.
- Tasks come out as **structured, validated JSON** (never free-text dumped into the task list).
- A usable daily plan is generated with one click.
- Tasks appear in my calendar/task app without manual copying.

## System layers

Each layer is planned and built one at a time (see build order below).

| # | Layer | Responsibility |
|---|-------|----------------|
| 1 | Meeting Capture | Upload audio (`.mp3`, `.wav`, `.m4a`) or live mic; save with metadata |
| 2 | Speech-to-Text | Transcribe audio (Whisper / Deepgram / AssemblyAI) with timestamped segments |
| 3 | Speaker Identification | Label who spoke (manual labels for MVP, diarization later) |
| 4 | LLM Orchestrator | Route jobs to models via base URL: cleanup, task extraction, planning, summaries |
| 5 | Task Extraction | Transcript → structured tasks (title, owner, due date, priority, dependencies) |
| 6 | Personal Task Filter | Keep only Anish's tasks, including indirect assignments |
| 7 | Planning Engine | Sort by priority, estimate time, chunk large tasks, add buffers, build the day plan |
| 8 | Storage | PostgreSQL/SQLite for tasks & meetings, object storage for audio, optional vector DB |
| 9 | Integrations | Notion, Google Calendar, Todoist, Slack, Email |
| 10 | Dashboard / UI | Meeting summary, my tasks, today's plan, overdue work |

## Architecture flow

```
Record meeting
→ upload audio
→ transcribe
→ identify speakers
→ extract tasks (LLM)
→ filter for Anish
→ create daily plan
→ save to database
→ sync to calendar/task app
```

## Design rules

1. **Structured output only** — the AI never creates tasks directly. Flow is:
   transcript → structured JSON → validation → task creation → plan generation.
2. **One model per job** — separate prompts/models for cleanup, extraction, planning, and follow-ups instead of one model doing everything.
3. **MVP first** — manual speaker labels and a simple UI are fine early; automation comes in later phases.

## Build order (phases)

- [ ] **Phase 1 — Meeting to transcript**: upload audio, transcribe, show transcript in UI — planned in [phase1.md](phase1.md)
- [ ] **Phase 2 — Summary & task extraction**: summary generation, task extraction, owner detection — planned in [phase2.md](phase2.md)
- [ ] **Phase 3 — Anish-only filter**: speaker diarization, people registry, 3-bucket task classification (mine/maybe/others) — planned in [phase3.md](phase3.md)
- [ ] **Phase 4 — Daily planner**: availability-aware scheduling, Google Calendar read+write, timetable ingestion, Gantt chart, planning chatbot — planned in [phase4.md](phase4.md)
- [ ] **Phase 5 — Notion sync & notifications**: two-way Notion task sync, meeting pages, digest notifications (morning/meeting/evening) — planned in [phase5.md](phase5.md)
- [ ] **Phase 6 — Smart assistant**: pgvector meeting memory, escalating overdue warnings, what-next suggestions, stats + estimate learning, weekly review — planned in [phase6.md](phase6.md)

## Tech stack

| Area | Choice |
|------|--------|
| Backend | Python + FastAPI |
| Speech-to-Text | Whisper (or Deepgram/AssemblyAI) |
| AI layer | Base URL with multi-model routing |
| Database | PostgreSQL (SQLite for early dev) |
| Queue | Redis + Celery or RQ |
| Frontend | React or Next.js |
| Object storage | S3-compatible |
| Deployment | Docker (optional) |

## Out of scope (for now)

- Real-time in-meeting suggestions
- Multi-user / team accounts (single user: Anish)
- Mobile app (dashboard is web-first; mobile later)
- Automatic speaker voice recognition (manual labels for MVP)
