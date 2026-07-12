# Self Planner

AI-powered personal meeting assistant. See [Goal.md](Goal.md) for the full vision and [phase1.md](phase1.md)–[phase6.md](phase6.md) for the build plan.

**Current state: Phase 4 complete (Google Calendar skipped by decision)** — meetings become classified tasks, an LLM estimates them, a deterministic planner schedules them into availability windows (work Mon–Fri 10–19, personal weekend afternoons, 25–90 min blocks, 10-min buffers, 4h deep work/day), and a chatbot at `/chat` manages tasks, answers schedule questions, and ingests timetables (image/PDF/CSV/text → confirmed busy blocks). Gantt view at `/gantt`; morning auto-replan + chat summary at 08:00.

## Stack

- **Backend**: FastAPI + SQLAlchemy (`backend/`)
- **Frontend**: Next.js 15 App Router (`frontend/`)
- **Infra**: PostgreSQL 16 (pgvector image) + MinIO via Docker Compose
- **STT**: faster-whisper (local, CPU, `small` model)
- **LLM**: any OpenAI-compatible endpoint (LiteLLM gateway); per-job models via `.env` (`LLM_MODEL_SUMMARY`, `LLM_MODEL_EXTRACT`)

## Prerequisites

- Docker Desktop (running)
- Python 3.13+, Node 20+
- ffmpeg on PATH (installed via `winget install Gyan.FFmpeg`)

## Run it

```powershell
# 1. Infra (Postgres :5432, MinIO :9000/:9001)
docker compose up -d

# 2. Backend (http://localhost:8000, docs at /docs)
cd backend
python -m venv .venv          # first time only
.\.venv\Scripts\pip install -r requirements.txt   # first time only
.\.venv\Scripts\uvicorn app.main:app --port 8000 --timeout-keep-alive 600

# 3. Frontend (http://localhost:3000)
cd frontend
npm install                   # first time only
npm run dev
```

Then open http://localhost:3000, upload an `.mp3`/`.wav`/`.m4a`, and wait for the transcript. The first upload downloads the Whisper model (~460 MB) — later uploads are much faster.

Config lives in `backend/.env` (DB URL, MinIO creds, `WHISPER_MODEL`, upload size limit).

## API

Base: `http://localhost:8000/api`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/meetings` | Upload audio (multipart `file`, optional `title`); transcribes synchronously |
| GET | `/meetings` | List meetings |
| GET | `/meetings/{id}` | Meeting detail with segments |
| DELETE | `/meetings/{id}` | Delete meeting + segments + tasks + audio object |
| POST | `/meetings/{id}/extract` | Re-run summary + task extraction (reconciles; edited tasks preserved) |
| GET | `/meetings/{id}/tasks` | Tasks for one meeting |
| GET | `/tasks?owner=&status=` | All tasks across meetings |
| PATCH | `/tasks/{id}` | Edit a task (sets `edited=true`, protecting it from re-extraction) |
| DELETE | `/tasks/{id}` | Delete a task |
| POST | `/tasks/{id}/confirm` · `/dismiss` | Maybe-mine inbox decisions (sticky, never overwritten) |
| PUT | `/meetings/{id}/speaker-map` | Map raw speaker labels to people; re-runs classification |
| POST | `/meetings/{id}/classify` | Re-run classification only |
| GET/POST/PATCH/DELETE | `/people` | People registry (names, aliases, is_me) |

Upload returns **202 immediately**; the pipeline (transcribe → diarize → extract → classify) runs in the background and the UI polls per-stage status. Diarization requires `HF_TOKEN` in `backend/.env` (+ accepting the pyannote model terms on Hugging Face); without it the pipeline skips diarization and the UI offers manual speaker labels.

## Notes

- Transcription is synchronous by design (Phase 1 decision); the UI holds a 10-minute timeout with a spinner. The `status` column already supports the Phase 3 switch to background processing.
- Audio is uploaded to MinIO **before** the DB row is inserted, and kept on transcription failure so retries are possible.
