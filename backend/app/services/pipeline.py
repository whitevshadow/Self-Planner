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
from . import classifier, diarizer, extraction, storage, transcriber, triage

logger = logging.getLogger(__name__)


def reclaim_orphans() -> None:
    """Fail meetings left mid-pipeline by a crash or restart.

    Stages run as in-process BackgroundTasks, so a process that just booted
    cannot have any in-flight work: every non-terminal row is orphaned by
    definition. Without this the row keeps its 'running' status forever and the
    UI polls it indefinitely. Re-transcribe restarts the pipeline from the audio.
    """
    from sqlalchemy import or_, select

    db = SessionLocal()
    try:
        orphans = db.scalars(
            select(Meeting).where(
                or_(
                    Meeting.status.in_(("uploaded", "transcribing")),
                    Meeting.diarize_status == "running",
                    Meeting.extract_status == "running",
                )
            )
        ).all()
        for meeting in orphans:
            if meeting.status in ("uploaded", "transcribing"):
                meeting.status = "failed"
                meeting.error = (
                    "Transcription was interrupted (the server restarted). "
                    "Press Re-transcribe to run it again."
                )
            if meeting.diarize_status == "running":
                meeting.diarize_status = "failed"
            if meeting.extract_status == "running":
                meeting.extract_status = "failed"
                meeting.extract_error = (
                    "Extraction was interrupted (the server restarted). "
                    "Press Re-extract to run it again."
                )
                meeting.extract_progress = None
        if orphans:
            db.commit()
            logger.warning("Reclaimed %d meeting(s) orphaned by a restart", len(orphans))
    except Exception:
        db.rollback()
        logger.exception("Orphan reclaim failed")
    finally:
        db.close()


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
        # Re-transcribe replaces the previous run's segments; deleting only
        # after a successful transcription keeps the old transcript on failure.
        db.query(Segment).filter(Segment.meeting_id == meeting.id).delete()
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


def extract_meeting(meeting_id) -> None:
    """Background re-extract entry point: fresh session, extract + classify."""
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            return
        _extract_and_classify_stage(db, meeting)
    except Exception:
        logger.exception("Re-extraction crashed for meeting %s", meeting_id)
    finally:
        db.close()


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
        return

    # Tasks that landed on me get their priority, duration, start date and
    # deadline filled in now, so they are schedulable without further input.
    # Best-effort: a triage failure leaves the tasks intact, just unenriched.
    try:
        mine = [t for t in meeting.tasks if t.assignment == "mine"]
        triage.triage_tasks(db, mine)
    except Exception:
        db.rollback()
        logger.exception("Triage failed for meeting %s", meeting.id)
