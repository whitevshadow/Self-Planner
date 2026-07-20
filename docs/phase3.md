# Phase 3 — Speaker Diarization & Anish-Only Filter

> Goal: know who spoke, know who owns each task, and surface **my** tasks — including indirectly assigned ones — with zero silent drops.
> Parent doc: [Goal.md](Goal.md) · Builds on: [phase1.md](phase1.md), [phase2.md](phase2.md)

## Decisions (locked)

| Decision | Choice | Notes |
|----------|--------|-------|
| Ambiguity handling | **3 buckets: mine / maybe / others** | Ambiguous tasks land in a "Maybe mine" inbox for confirm/dismiss. |
| Speakers | **Auto diarization (pyannote.audio)** | Detects Speaker 1/2/3 automatically; you map names once per meeting. Manual override always available. |
| People | **Registry with aliases** | `people` table (canonical name, aliases, `is_me`), managed in a settings page, fed to the LLM as roster context. |
| Extras | **All three** | Transcript highlighting, per-task classification reasoning, My-tasks dashboard as homepage. |

### pyannote prerequisites & risk

- Requires a free Hugging Face account + access token (`HF_TOKEN` in `.env`), and one-time acceptance of the `pyannote/speaker-diarization-3.1` model terms on the HF website.
- CPU diarization of a 1-hour meeting can take several minutes (it's slower than Whisper). Stacked on transcription + three LLM jobs, the synchronous upload request is no longer viable. **Phase 3 therefore includes the background-processing switch sketched in phase1.md**: upload returns `202` with the meeting immediately, the pipeline (transcribe → diarize → extract → classify) runs via FastAPI `BackgroundTasks`, and the UI polls `GET /meetings/{id}` showing per-stage status (`status`, `diarize_status`, `extract_status`). No schema change needed — the columns already exist.
- **Fallback**: if diarization fails or `HF_TOKEN` is unset, the pipeline continues without speakers (Phase 2 behavior) and the transcript view falls back to manual speaker labeling per segment. Diarization failure must never block transcription or extraction.

## Scope

**In:**
- Diarization service: audio → speaker turns → speakers assigned to Whisper segments
- Speaker-mapping UI: rename "Speaker 1/2/3" → real people (from the registry) per meeting
- `people` registry with aliases + settings page; `is_me` marks Anish
- Classification job (LLM job 3): every task → `mine | maybe | others` + one-line reason
- "Maybe mine" inbox: confirm (→ mine) or dismiss (→ others)
- My-tasks dashboard as the app homepage
- Transcript highlighting: segments that produced my tasks; click task → jump to quote

**Out (later phases):**
- Voice fingerprinting across meetings (auto-recognizing "this voice = Anish" from history)
- Planning/scheduling (Phase 4)
- Any external sync (Phase 5)

## Architecture

```
Phase 1 pipeline: upload → MinIO → transcribe (Whisper)
      │
      ├──► [Diarization]  services/diarizer.py (pyannote)
      │       audio → [(start, end, "SPEAKER_00"), ...]
      │       align with Whisper segments by time overlap
      │       segments.speaker = "SPEAKER_00" (raw label)
      │       (on failure: skip, log, continue)
      ▼
Phase 2 pipeline: summary + task extraction
      │    (extraction prompt now includes speaker-tagged transcript
      │     when available: "[SPEAKER_00] I'll take the auth work.")
      ▼
[Classification]  LLM job 3 — services/classifier.py
      │    input: tasks + speaker-tagged transcript + people roster
      │    output per task: {assignment: mine|maybe|others, reason: str}
      ▼
PostgreSQL: tasks.assignment, tasks.assignment_reason
      ▼
UI: My-tasks dashboard (homepage) · Maybe-mine inbox · highlighted transcript
```

### Speaker → person resolution

1. Diarization produces raw labels (`SPEAKER_00`, `SPEAKER_01`) on segments.
2. On the meeting page, a **speaker mapping bar** lists each raw label with a sample quote and a dropdown of people from the registry (+ "add new person").
3. Saving the mapping rewrites `segments.speaker` to the canonical person name and **re-runs classification** (not extraction) so first-person assignments resolve: "[Anish] I'll take that" → mine.
4. Classification runs even before mapping — unmapped speakers just mean more tasks land in "maybe" instead of "mine". Mapping upgrades them.

## Configuration (`backend/.env` additions)

```env
HF_TOKEN=hf_...                     # optional; diarization skipped if unset
DIARIZATION_MODEL=pyannote/speaker-diarization-3.1
LLM_MODEL_CLASSIFY=model-name-c     # third routed job
```

## Database changes

```sql
CREATE TABLE people (
    id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name    TEXT NOT NULL UNIQUE,          -- canonical: "Anish"
    aliases JSONB NOT NULL DEFAULT '[]',   -- ["anish", "AB", "Anish B."]
    is_me   BOOLEAN NOT NULL DEFAULT false -- exactly one row true (enforced in app)
);

-- segments already have speaker (reserved in Phase 1)
ALTER TABLE segments ADD COLUMN speaker_raw TEXT;  -- pyannote label, kept for re-mapping

-- meetings: diarization state + speaker mapping
ALTER TABLE meetings ADD COLUMN diarize_status TEXT NOT NULL DEFAULT 'pending';
                     -- pending | running | done | failed | skipped
ALTER TABLE meetings ADD COLUMN speaker_map JSONB NOT NULL DEFAULT '{}';
                     -- {"SPEAKER_00": "Anish", "SPEAKER_01": "Rahul"}

-- tasks: classification results
ALTER TABLE tasks ADD COLUMN assignment        TEXT NOT NULL DEFAULT 'others';
                  -- mine | maybe | others
ALTER TABLE tasks ADD COLUMN assignment_reason TEXT;
ALTER TABLE tasks ADD COLUMN assignment_source TEXT NOT NULL DEFAULT 'llm';
                  -- llm | user   (user = confirmed/dismissed from inbox; never overwritten by re-runs)
ALTER TABLE tasks ADD COLUMN segment_idx       INT;  -- best-match segment for highlighting

CREATE INDEX idx_tasks_assignment ON tasks (assignment);
```

Rules:
- `assignment_source='user'` (inbox confirm/dismiss, or manual edit) is **never overwritten** by re-classification — same protection pattern as Phase 2's `edited` flag.
- `segment_idx` is found by fuzzy-matching `source_quote` against segment texts at classification time (fallback: null → no highlight).

## Classification job (LLM job 3)

Separate call from extraction — extraction finds tasks, classification decides whose they are. Keeping them separate means re-mapping speakers only re-runs the cheap classification step.

**Input:** task list (title, owner, source_quote), speaker-tagged transcript excerpt around each quote, people roster with aliases, and which person `is_me`.

**Output JSON per task:**

```json
{
  "task_id": "…",
  "assignment": "mine",
  "reason": "Directly named: 'Anish will integrate authentication'",
  "owner_normalized": "Anish"
}
```

**Prompt rules:**
- `mine`: directly named (any alias), or the mapped `is_me` speaker volunteered ("I'll handle it")
- `maybe`: indirect/unassigned but plausibly mine — "someone should test this", "can you check?" said *to* an unmapped speaker, owner is null but topic matches my open work
- `others`: clearly someone else's
- Always give a one-line reason; never guess `mine` without evidence — when unsure, prefer `maybe` (the inbox exists to catch these)
- `owner_normalized` must be a roster name or null; it updates `tasks.owner`

Validation + one retry, same as Phase 2. Runs automatically after extraction, after speaker-map saves, and via the Re-extract button.

## API changes

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST | `/people` · PATCH/DELETE `/people/{id}` | Manage the registry (name, aliases, is_me). |
| PUT | `/meetings/{id}/speaker-map` | Save `{raw_label: person_name}`; rewrites segment speakers, re-runs classification. |
| POST | `/meetings/{id}/classify` | Re-run classification only. |
| POST | `/tasks/{id}/confirm` | Maybe → mine (`assignment_source=user`). |
| POST | `/tasks/{id}/dismiss` | Maybe → others (`assignment_source=user`). |
| GET | `/tasks?assignment=mine` | Existing endpoint gains `assignment` filter. |

`GET /meetings/{id}` grows: `diarize_status`, `speaker_map`, and per-segment `speaker` / `speaker_raw`.

## Frontend changes

### `/` — **My Tasks dashboard (new homepage)**
- My tasks across all meetings, sorted by due date; overdue flagged
- **Maybe-mine inbox** at the top when non-empty: task + reason + source quote, Confirm / Dismiss buttons
- Each task shows its classification reason on hover/expand, links to its meeting
- Meetings list moves to `/meetings`

### `/meetings/[id]` — additions
- **Speaker mapping bar** (when diarization found speakers): each raw label + sample quote + person dropdown; Save re-runs classification
- Transcript segments prefixed with speaker names, colored per speaker
- **Highlighting**: segments that produced my tasks get a highlight; clicking a task scrolls to and flashes its source segment
- If `diarize_status` is `failed`/`skipped`: banner + per-segment manual speaker dropdown (the fallback path)

### `/settings/people` — new page
- Table of people: name, aliases (tag input), is_me radio; add/edit/delete

## Build steps (in order)

1. **Background pipeline switch**: upload returns `202` immediately; transcribe/diarize/extract/classify run in `BackgroundTasks`; UI polls with per-stage status
2. **People registry**: table, CRUD API, settings page; seed "Anish" with `is_me=true`
3. **Diarization service**: pyannote wrapper, segment alignment by time overlap, graceful skip on missing token/failure; test standalone on a sample file
4. **Pipeline wiring**: diarization between transcription and extraction; `speaker_raw` on segments; extraction prompt includes speaker tags when present
5. **Speaker mapping**: `speaker_map` save endpoint + rewrite logic; mapping bar UI; manual per-segment fallback UI
6. **Classification job**: prompt + schema, `LLM_MODEL_CLASSIFY` routing, `segment_idx` fuzzy match, user-override protection
7. **Inbox + dashboard**: confirm/dismiss endpoints, My-tasks homepage with inbox, move meetings list to `/meetings`
8. **Highlighting**: task → segment linking in the transcript view
9. **End-to-end test**: multi-speaker recording → speakers detected → map names → "I'll do X" task lands in mine; ambiguous task lands in inbox; confirm survives re-classification

## Definition of done

- [ ] A multi-speaker meeting gets automatic speaker labels; mapping them to people takes seconds
- [ ] Diarization failure or missing HF token degrades gracefully — pipeline still completes, manual labeling available
- [ ] "Anish will do X", "[Anish speaking] I'll do X", and alias mentions all classify as **mine**
- [ ] Vague tasks ("someone should…") appear in the Maybe-mine inbox with a reason — never silently dropped or silently claimed
- [ ] Confirm/dismiss decisions survive re-extraction and re-classification
- [ ] Homepage shows my tasks across all meetings, sorted by due date
- [ ] Clicking one of my tasks jumps to the highlighted transcript segment that produced it
- [ ] Classification model is swappable via `.env` alone
