"""Summary + task extraction pipeline (LLM jobs 1 and 2).

Each job is independent: a summary failure doesn't block task extraction and
vice versa. Task reconciliation keeps ids stable across re-extracts and never
touches user-edited rows.
"""
import difflib
import logging

from sqlalchemy.orm import Session

from ..models import Meeting, Task
from ..schemas import ExtractResult, SummaryResult
from . import orchestrator, prompts

logger = logging.getLogger(__name__)

TITLE_MATCH_THRESHOLD = 0.75


def build_transcript(meeting: Meeting) -> str:
    lines = []
    for seg in meeting.segments:
        mm, ss = divmod(int(seg.start_sec), 60)
        prefix = f"[{mm:02d}:{ss:02d}]"
        speaker = seg.speaker or seg.speaker_raw  # canonical name, else raw pyannote label
        if speaker:
            prefix += f" [{speaker}]"
        lines.append(f"{prefix} {seg.text}")
    return "\n".join(lines)


def run_extraction(db: Session, meeting: Meeting) -> None:
    """Run both jobs, collect errors, commit results + status atomically per stage."""
    meeting.extract_status = "running"
    meeting.extract_error = None
    db.commit()

    transcript = build_transcript(meeting)
    if not transcript.strip():
        meeting.extract_status = "failed"
        meeting.extract_error = "Transcript is empty"
        db.commit()
        return

    errors: list[str] = []

    try:
        result = orchestrator.run_json_job(
            "summary", prompts.SUMMARY_SYSTEM, prompts.summary_user(transcript), SummaryResult
        )
        meeting.summary = result.summary
        meeting.decisions = result.decisions
    except Exception as exc:
        logger.exception("Summary job failed for meeting %s", meeting.id)
        errors.append(f"summary: {exc}")

    try:
        meeting_day = meeting.created_at.date()
        result = orchestrator.run_json_job(
            "extract",
            prompts.EXTRACT_SYSTEM,
            prompts.extract_user(transcript, meeting_day.isoformat(), meeting_day.strftime("%A")),
            ExtractResult,
        )
        result.tasks = _dedupe_tasks(result.tasks)
        _reconcile_tasks(db, meeting, result)
    except Exception as exc:
        logger.exception("Extraction job failed for meeting %s", meeting.id)
        errors.append(f"extract: {exc}")

    meeting.extract_status = "failed" if errors else "done"
    meeting.extract_error = "; ".join(str(e)[:500] for e in errors) if errors else None
    db.commit()


def _dedupe_tasks(tasks: list) -> list:
    """Drop near-identical extracted tasks (same action mentioned twice)."""
    kept = []
    for t in tasks:
        duplicate = any(
            difflib.SequenceMatcher(None, k.title.lower(), t.title.lower()).ratio() >= 0.85
            and (k.owner or "").lower() == (t.owner or "").lower()
            for k in kept
        )
        if not duplicate:
            kept.append(t)
    return kept


def _reconcile_tasks(db: Session, meeting: Meeting, result: ExtractResult) -> None:
    """Match new extraction against existing tasks by fuzzy title.

    Matched tasks are updated in place (id preserved); edited tasks are never
    modified. Stale unmatched tasks are deleted only if unedited. New tasks
    are inserted. All within the caller's transaction.
    """
    existing = list(meeting.tasks)
    unmatched = set(id(t) for t in existing)

    for new in result.tasks:
        best, best_score = None, 0.0
        for task in existing:
            if id(task) not in unmatched:
                continue
            score = difflib.SequenceMatcher(
                None, task.title.lower().strip(), new.title.lower().strip()
            ).ratio()
            if score > best_score:
                best, best_score = task, score

        if best is not None and best_score >= TITLE_MATCH_THRESHOLD:
            unmatched.discard(id(best))
            if not best.edited:
                best.title = new.title
                best.owner = new.owner
                best.due_date = new.due_date
                best.priority = new.priority
                best.dependencies = new.dependencies
                best.source_quote = new.source_quote
        else:
            db.add(
                Task(
                    meeting_id=meeting.id,
                    title=new.title,
                    owner=new.owner,
                    due_date=new.due_date,
                    priority=new.priority,
                    dependencies=new.dependencies,
                    source_quote=new.source_quote,
                )
            )

    for task in existing:
        if id(task) in unmatched and not task.edited:
            db.delete(task)
