"""Background processing pipeline: transcribe → diarize → extract → classify.

Runs via FastAPI BackgroundTasks after upload returns 202. Each stage commits
its results and status flag together; a failure in one stage never corrupts
another. Uses its own DB session (the request session is gone by run time).
"""
import logging
import os
import tempfile

from ..db import SessionLocal
from ..models import Meeting
from . import classifier, diarizer, extraction, storage, transcriber

logger = logging.getLogger(__name__)


def process_meeting(meeting_id) -> None:
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            return

        ext = os.path.splitext(meeting.audio_key)[1]
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = tmp.name
            storage.download_audio(meeting.audio_key, tmp_path)

            _transcribe_stage(db, meeting, tmp_path)
            if meeting.status != "done":
                return  # transcription failed; nothing downstream can run
            _diarize_stage(db, meeting, tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        _extract_and_classify_stage(db, meeting)
    except Exception:
        logger.exception("Pipeline crashed for meeting %s", meeting_id)
    finally:
        db.close()


def _transcribe_stage(db, meeting: Meeting, audio_path: str) -> None:
    from ..models import Segment

    try:
        segments, duration = transcriber.transcribe(audio_path)
        for seg in segments:
            db.add(Segment(meeting_id=meeting.id, **seg))
        meeting.duration_sec = duration
        meeting.status = "done"
        db.commit()
    except Exception as exc:
        db.rollback()
        meeting.status = "failed"
        meeting.error = str(exc)[:2000]
        db.commit()
        logger.exception("Transcription failed for meeting %s", meeting.id)


def _diarize_stage(db, meeting: Meeting, audio_path: str) -> None:
    if not diarizer.available():
        meeting.diarize_status = "skipped"
        db.commit()
        return
    meeting.diarize_status = "running"
    db.commit()
    try:
        turns = diarizer.diarize(audio_path)
        db.refresh(meeting)
        diarizer.assign_speakers(meeting.segments, turns)
        meeting.diarize_status = "done"
        db.commit()
    except Exception as exc:
        # Diarization failure must never block extraction — skip and continue.
        db.rollback()
        meeting.diarize_status = "failed"
        db.commit()
        logger.exception("Diarization failed for meeting %s: %s", meeting.id, exc)


def _extract_and_classify_stage(db, meeting: Meeting) -> None:
    extraction.run_extraction(db, meeting)  # manages extract_status itself
    if meeting.extract_status != "done":
        return
    try:
        classifier.run_classification(db, meeting)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Classification failed for meeting %s", meeting.id)
