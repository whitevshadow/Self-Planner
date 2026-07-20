import os
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..db import get_db
from ..models import Meeting, Person, Segment, Task
from ..schemas import MeetingDetail, MeetingListItem, MeetingTextIn, TaskOut
from ..services import classifier, pipeline, storage

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".ogg"}
CONTENT_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".webm": "audio/webm", ".ogg": "audio/ogg"}

# "Anish: let's ship it" → speaker "Anish". Leads with a letter so clock times
# ("10:30") and note prefixes ("http://") don't parse as speakers; the name is
# capped to a handful of words so mid-sentence colons don't get mistaken for one.
_SPEAKER_PREFIX = re.compile(r"^([A-Za-z][\w.'\- ]{0,40}?):\s+(.+)$")


def _segments_from_text(text: str) -> list[dict]:
    """Split pasted transcript/notes into segments the pipeline can extract from.

    One segment per non-blank line. A leading ``Name:`` is lifted into the
    segment speaker so the classifier can still spot first-person assignments.
    Timestamps are 0 — pasted text has none, and nothing downstream requires them.
    """
    segments: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        speaker = None
        match = _SPEAKER_PREFIX.match(line)
        if match and len(match.group(1).split()) <= 4:
            speaker, line = match.group(1).strip(), match.group(2).strip()
            if not line:
                continue
        segments.append(
            {"idx": len(segments), "start_sec": 0.0, "end_sec": 0.0, "text": line, "speaker": speaker}
        )
    return segments


@router.post("", response_model=MeetingDetail, status_code=202)
def upload_meeting(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Upload returns 202 immediately; transcribe → diarize → extract → classify
    run in the background. The UI polls GET /meetings/{id} for per-stage status."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(422, f"Unsupported file type '{ext}'. Allowed: .mp3, .wav, .m4a")

    data = file.file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB limit")
    if not data:
        raise HTTPException(422, "Empty file")

    meeting_id = uuid.uuid4()
    audio_key = f"{meeting_id}{ext}"

    # Upload audio before inserting the row: an orphan object is harmless,
    # a row without audio is not.
    storage.upload_audio(audio_key, data, CONTENT_TYPES[ext])

    meeting = Meeting(
        id=meeting_id,
        title=title or os.path.splitext(file.filename or "recording")[0],
        filename=file.filename or "recording",
        audio_key=audio_key,
        status="transcribing",
    )
    db.add(meeting)
    db.commit()

    background.add_task(pipeline.process_meeting, meeting_id)
    return _get_meeting_or_404(db, meeting_id)


@router.post("/text", response_model=MeetingDetail, status_code=202)
def create_from_text(body: MeetingTextIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Create a meeting from pasted transcript/notes — no audio, no transcription.

    Returns 202 immediately; extraction → classification → triage run in the
    background exactly as for an uploaded recording. The UI polls GET /meetings/{id}.
    """
    segments = _segments_from_text(body.text)
    if not segments:
        raise HTTPException(422, "No usable text — paste a transcript or some notes")

    meeting_id = uuid.uuid4()
    meeting = Meeting(
        id=meeting_id,
        title=(body.title or "").strip() or "Pasted notes",
        filename="pasted.txt",
        audio_key="",  # sentinel: this meeting has no audio (never re-transcribable)
        status="done",  # transcript already exists; skip straight to extraction
        diarize_status="skipped",
        extract_status="running",  # hold the re-extract guard + poll immediately
    )
    db.add(meeting)
    for seg in segments:
        db.add(Segment(meeting_id=meeting_id, **seg))
    db.commit()

    background.add_task(pipeline.extract_meeting, meeting_id)
    return _get_meeting_or_404(db, meeting_id)


@router.post("/{meeting_id}/retranscribe", response_model=MeetingDetail, status_code=202)
def re_transcribe(meeting_id: uuid.UUID, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Full re-run from the stored audio: transcribe → diarize → extract →
    classify. Returns 202 immediately; the UI polls GET /meetings/{id}.
    Task reconciliation preserves edited tasks as usual."""
    meeting = _get_meeting_or_404(db, meeting_id)
    if not meeting.audio_key:
        raise HTTPException(422, "This meeting was pasted as text and has no audio to re-transcribe. Use Re-extract instead.")
    if meeting.status in ("uploaded", "transcribing") or meeting.extract_status == "running":
        raise HTTPException(409, "Meeting is already being processed")
    meeting.status = "transcribing"
    meeting.error = None
    meeting.diarize_status = "pending"
    meeting.extract_status = "pending"
    meeting.extract_error = None
    meeting.extract_progress = None
    db.commit()
    background.add_task(pipeline.process_meeting, meeting_id)
    return _get_meeting_or_404(db, meeting_id)


@router.post("/{meeting_id}/extract", response_model=MeetingDetail, status_code=202)
def re_extract(meeting_id: uuid.UUID, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Returns 202 immediately; batched extraction + classification run in the
    background. The UI polls GET /meetings/{id} for extract_status/progress."""
    meeting = _get_meeting_or_404(db, meeting_id)
    if meeting.status != "done":
        raise HTTPException(409, "Meeting has no completed transcript to extract from")
    # Row-level guard: a concurrent extract becomes a no-op instead of a double run.
    if meeting.extract_status == "running":
        raise HTTPException(409, "Extraction already running")
    # Mark running before returning so the guard holds and the UI polls right away.
    meeting.extract_status = "running"
    meeting.extract_error = None
    meeting.extract_progress = None
    db.commit()
    background.add_task(pipeline.extract_meeting, meeting_id)
    return _get_meeting_or_404(db, meeting_id)


@router.post("/{meeting_id}/classify", response_model=MeetingDetail)
def re_classify(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    meeting = _get_meeting_or_404(db, meeting_id)
    try:
        classifier.run_classification(db, meeting)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Classification failed: {exc}")
    return _get_meeting_or_404(db, meeting_id)


@router.put("/{meeting_id}/speaker-map", response_model=MeetingDetail)
def save_speaker_map(
    meeting_id: uuid.UUID,
    mapping: dict[str, str],
    db: Session = Depends(get_db),
):
    """Save {raw_label: person_name}; rewrites segment speakers atomically,
    then re-runs classification so first-person assignments resolve."""
    meeting = _get_meeting_or_404(db, meeting_id)

    registry = {p.name for p in db.scalars(select(Person)).all()}
    unknown = [name for name in mapping.values() if name and name not in registry]
    if unknown:
        raise HTTPException(422, f"Not in people registry: {', '.join(unknown)}. Add them first.")

    for seg in meeting.segments:
        if seg.speaker_raw and seg.speaker_raw in mapping:
            seg.speaker = mapping[seg.speaker_raw] or None
    meeting.speaker_map = mapping
    db.commit()  # speaker rewrite + map commit together

    try:
        classifier.run_classification(db, meeting)
        db.commit()
    except Exception:
        db.rollback()  # mapping is saved; classification can be retried separately

    return _get_meeting_or_404(db, meeting_id)


@router.put("/{meeting_id}/segments/{segment_idx}/speaker", response_model=MeetingDetail)
def set_segment_speaker(
    meeting_id: uuid.UUID,
    segment_idx: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """Manual fallback when diarization failed: label one segment's speaker."""
    meeting = _get_meeting_or_404(db, meeting_id)
    seg = next((s for s in meeting.segments if s.idx == segment_idx), None)
    if seg is None:
        raise HTTPException(404, "Segment not found")
    speaker = (body.get("speaker") or "").strip()
    if speaker and not db.scalar(select(Person).where(Person.name == speaker)):
        raise HTTPException(422, f"'{speaker}' is not in the people registry")
    seg.speaker = speaker or None
    db.commit()
    return _get_meeting_or_404(db, meeting_id)


_AUDIO_CHUNK = 256 * 1024


@router.get("/{meeting_id}/audio")
def stream_audio(meeting_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """Stream the meeting audio with HTTP Range support so the <audio> element
    can seek to any transcript segment. Pasted-text meetings have no audio."""
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if not meeting.audio_key:
        raise HTTPException(404, "This meeting has no audio")
    try:
        size, content_type = storage.stat_audio(meeting.audio_key)
    except Exception:
        raise HTTPException(404, "Audio object not found")

    start, end = 0, size - 1
    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        rng = range_header.split("=", 1)[1].split(",")[0].strip()
        s_part, _, e_part = rng.partition("-")
        if s_part.strip():
            start = int(s_part)
        end = int(e_part) if e_part.strip() else size - 1
        if start > end or start >= size:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        end = min(end, size - 1)

    length = end - start + 1

    def body():
        resp = storage.get_audio_stream(meeting.audio_key, offset=start, length=length)
        try:
            yield from resp.stream(_AUDIO_CHUNK)
        finally:
            resp.close()
            resp.release_conn()

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": content_type,
    }
    status = 200
    if range_header:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        status = 206
    return StreamingResponse(body(), status_code=status, headers=headers, media_type=content_type)


@router.get("/{meeting_id}/tasks", response_model=list[TaskOut])
def meeting_tasks(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    meeting = _get_meeting_or_404(db, meeting_id)
    return meeting.tasks


@router.get("", response_model=list[MeetingListItem])
def list_meetings(db: Session = Depends(get_db)):
    # "__chat__" is the synthetic container for chat-created tasks, not a real meeting.
    return db.scalars(
        select(Meeting).where(Meeting.title != "__chat__").order_by(Meeting.created_at.desc())
    ).all()


@router.get("/{meeting_id}", response_model=MeetingDetail)
def get_meeting(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get_meeting_or_404(db, meeting_id)


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    meeting = db.get(Meeting, meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    audio_key = meeting.audio_key
    db.delete(meeting)  # cascades to segments + tasks
    db.commit()
    if audio_key:  # pasted-text meetings have no audio object
        try:
            storage.delete_audio(audio_key)
        except Exception:
            pass  # orphan object in MinIO is harmless


def _get_meeting_or_404(db: Session, meeting_id: uuid.UUID) -> Meeting:
    meeting = db.scalars(
        select(Meeting)
        .options(selectinload(Meeting.segments), selectinload(Meeting.tasks))
        .where(Meeting.id == meeting_id)
        .execution_options(populate_existing=True)  # refresh collections changed earlier in this request
    ).first()
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    return meeting
