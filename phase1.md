# Phase 1 — Meeting to Transcript

> Goal: upload a meeting recording, transcribe it locally with Whisper, and view the transcript in a Next.js UI.
> Parent doc: [Goal.md](Goal.md)

## Decisions (locked)

| Decision | Choice | Notes |
|----------|--------|-------|
| STT engine | **Local Whisper** (`faster-whisper`) | Free, offline, no API key. CPU is fine for MVP; GPU speeds it up later. |
| Frontend | **Next.js from day one** | Real frontend now, no rewrite later. Talks to FastAPI over REST. |
| Processing | **Synchronous** | Upload request waits for transcription to finish. Simplest code path. |
| Storage | **PostgreSQL + S3-compatible (MinIO)** | Production storage from day one, run locally via Docker Compose. |

### Known risk: synchronous + local Whisper

A 60-minute recording on CPU can take several minutes to transcribe, and the HTTP request stays open the whole time.

Mitigations built into this design:
- Frontend upload call uses a **10-minute client timeout** and shows a "Transcribing…" spinner.
- Uvicorn runs with `--timeout-keep-alive 600`.
- The `meetings` table already has a `status` column (`uploaded / transcribing / done / failed`), so switching to `BackgroundTasks` or Celery later is an internal change — **no API or schema change needed**.
- If long files become painful, the upgrade path is: same endpoint returns `202` immediately, UI polls `GET /meetings/{id}` until `status = done`.

## Scope

**In:**
- Upload `.mp3`, `.wav`, `.m4a` from the browser
- Store audio in MinIO, metadata + transcript in PostgreSQL
- Transcribe with faster-whisper, keeping timestamped segments
- Meetings list page + meeting detail page showing the transcript
- Delete a meeting

**Out (later phases):**
- Live microphone capture
- Speaker labels/diarization (Phase 3 — but the schema reserves a `speaker` field now)
- Summaries, tasks, LLM anything (Phase 2+)
- Auth (single user)

## Architecture

```
Next.js (localhost:3000)
   │  multipart POST /api/meetings  (proxied or direct)
   ▼
FastAPI (localhost:8000)
   │ 1. validate file (extension, size)
   │ 2. upload audio → MinIO  (bucket: meetings-audio)
   │ 3. insert meeting row → PostgreSQL (status=transcribing)
   │ 4. run faster-whisper on the file (synchronous)
   │ 5. save transcript + segments → PostgreSQL (status=done)
   │ 6. return meeting JSON with transcript
   ▼
PostgreSQL (Docker)        MinIO (Docker)
meetings, segments         raw audio files
```

## Folder structure

```
self_planner/
├── Goal.md
├── phase1.md
├── docker-compose.yml          # postgres + minio
├── backend/
│   ├── pyproject.toml          # or requirements.txt
│   ├── .env                    # DB URL, MinIO creds (gitignored)
│   └── app/
│       ├── main.py             # FastAPI app, CORS, router mounting
│       ├── config.py           # settings via pydantic-settings
│       ├── db.py               # SQLAlchemy engine/session
│       ├── models.py           # Meeting, Segment ORM models
│       ├── schemas.py          # Pydantic request/response models
│       ├── routers/
│       │   └── meetings.py     # upload, list, detail, delete
│       └── services/
│           ├── storage.py      # MinIO upload/download/delete
│           └── transcriber.py  # faster-whisper wrapper
└── frontend/
    ├── package.json
    └── src/
        ├── app/
        │   ├── page.tsx            # meetings list + upload
        │   └── meetings/[id]/page.tsx  # transcript view
        ├── components/
        │   ├── UploadForm.tsx      # file picker, progress, spinner
        │   ├── MeetingCard.tsx
        │   └── TranscriptView.tsx  # segments with timestamps
        └── lib/api.ts              # typed fetch helpers → FastAPI
```

## Database schema

```sql
CREATE TABLE meetings (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title        TEXT NOT NULL,
    filename     TEXT NOT NULL,           -- original upload name
    audio_key    TEXT NOT NULL,           -- MinIO object key
    duration_sec REAL,
    status       TEXT NOT NULL DEFAULT 'uploaded',
                 -- uploaded | transcribing | done | failed
    error        TEXT,                    -- failure reason if status=failed
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE segments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    idx        INT  NOT NULL,             -- segment order
    start_sec  REAL NOT NULL,
    end_sec    REAL NOT NULL,
    text       TEXT NOT NULL,
    speaker    TEXT                       -- NULL in Phase 1; filled in Phase 3
);

CREATE INDEX idx_segments_meeting ON segments (meeting_id, idx);
```

Full transcript text is derived by joining segments — no duplicated `transcript` column to keep in sync.

## API design

Base URL: `http://localhost:8000/api`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/meetings` | Upload audio (multipart: `file`, optional `title`). Transcribes synchronously; returns full meeting with segments. |
| GET | `/meetings` | List meetings (id, title, status, duration, created_at). |
| GET | `/meetings/{id}` | Meeting detail with all segments. |
| DELETE | `/meetings/{id}` | Delete meeting row + segments + MinIO object. |

### Response shape (GET /meetings/{id})

```json
{
  "id": "3f6c…",
  "title": "Sprint planning",
  "status": "done",
  "duration_sec": 1840.5,
  "created_at": "2026-07-11T10:30:00Z",
  "segments": [
    { "idx": 0, "start_sec": 12.4, "end_sec": 18.1, "text": "The API will be ready Friday.", "speaker": null }
  ]
}
```

### Validation rules

- Allowed extensions: `.mp3`, `.wav`, `.m4a` (reject others with 422)
- Max file size: 200 MB (413 if exceeded)
- Title defaults to the filename without extension
- On transcription failure: set `status=failed`, store `error`, return 500 with detail — audio stays in MinIO so it can be retried

## Transcription service

```python
# services/transcriber.py — the only place Whisper is touched
from faster_whisper import WhisperModel

model = WhisperModel("small", device="cpu", compute_type="int8")  # loaded once at startup

def transcribe(path: str) -> list[SegmentDict]:
    segments, info = model.transcribe(path, vad_filter=True)
    return [{"idx": i, "start_sec": s.start, "end_sec": s.end, "text": s.text.strip()}
            for i, s in enumerate(segments)]
```

- Model: start with `small` (good accuracy/speed balance on CPU); config-switchable via `.env` (`WHISPER_MODEL=small`).
- `ffmpeg` must be installed on the machine (faster-whisper needs it for m4a/mp3 decoding).
- Model loads once at app startup, not per request.

## docker-compose.yml (infrastructure only)

```yaml
services:
  db:
    image: pgvector/pgvector:pg16   # postgres 16 + pgvector baked in (needed by Phase 6; free now)
    environment:
      POSTGRES_USER: planner
      POSTGRES_PASSWORD: planner
      POSTGRES_DB: self_planner
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports: ["9000:9000", "9001:9001"]
    volumes: [miniodata:/data]

volumes:
  pgdata:
  miniodata:
```

Backend and frontend run natively during dev (`uvicorn`, `npm run dev`); only infra is containerized.

## Frontend pages

### `/` — Meetings list + upload
- Upload form: file picker, optional title, submit button
- During upload/transcription: progress → "Transcribing… this can take a few minutes" spinner (10-min fetch timeout)
- List of meeting cards: title, date, duration, status badge; click → detail
- Delete button per card (with confirm)

### `/meetings/[id]` — Transcript view
- Header: title, date, duration
- Segment list: `[00:12] The API will be ready Friday.` (timestamp formatted mm:ss)
- If `status=failed`: show the error message

## Build steps (in order)

1. **Infra**: write `docker-compose.yml`, start Postgres + MinIO, create `meetings-audio` bucket on startup
2. **Backend skeleton**: FastAPI app, config, DB models + table creation, CORS for localhost:3000
3. **Storage service**: MinIO upload/delete helpers
4. **Transcriber service**: faster-whisper wrapper, test on a sample audio file standalone
5. **Meetings router**: POST upload (validate → MinIO → DB → transcribe → save), GET list, GET detail, DELETE
6. **Frontend skeleton**: Next.js app, `lib/api.ts`, meetings list page
7. **Upload flow**: UploadForm with spinner + long timeout
8. **Transcript view**: detail page with timestamped segments
9. **End-to-end test**: upload a real recording, verify transcript renders, delete works

## Definition of done

- [ ] `docker compose up` brings up Postgres + MinIO
- [ ] Uploading an `.mp3`/`.wav`/`.m4a` from the browser produces a transcript
- [ ] Transcript shows timestamped segments on the detail page
- [ ] Meetings list shows all uploads with status
- [ ] Deleting a meeting removes the DB rows and the MinIO object
- [ ] Invalid file types and oversized files are rejected with clear errors
- [ ] A failed transcription shows `failed` status with an error message, not a crash
