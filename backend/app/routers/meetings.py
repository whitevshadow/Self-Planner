import os
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..db import get_db
from ..models import Meeting, Person, Task
from ..schemas import MeetingDetail, MeetingListItem, TaskOut
from ..services import classifier, extraction, pipeline, storage

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a"}
CONTENT_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}


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


@router.post("/{meeting_id}/extract", response_model=MeetingDetail)
def re_extract(meeting_id: uuid.UUID, db: Session = Depends(get_db)):
    meeting = _get_meeting_or_404(db, meeting_id)
    if meeting.status != "done":
        raise HTTPException(409, "Meeting has no completed transcript to extract from")
    # Row-level guard: a concurrent extract becomes a no-op instead of a double run.
    if meeting.extract_status == "running":
        raise HTTPException(409, "Extraction already running")
    try:
        extraction.run_extraction(db, meeting)
        if meeting.extract_status == "done":
            classifier.run_classification(db, meeting)
            db.commit()
    except Exception as exc:
        db.rollback()
        meeting.extract_status = "failed"
        meeting.extract_error = str(exc)[:2000]
        db.commit()
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
