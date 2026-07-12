"""Task classification (LLM job 3): every task → mine | maybe | others.

Separate from extraction so re-mapping speakers only re-runs this cheap step.
User decisions (assignment_source='user') are never overwritten.
"""
import difflib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Meeting, Person, Task
from ..schemas import ClassifyResult
from . import orchestrator, prompts
from .extraction import build_transcript

logger = logging.getLogger(__name__)


def run_classification(db: Session, meeting: Meeting) -> None:
    tasks = [t for t in meeting.tasks if t.status != "dropped"]
    if not tasks:
        return

    people = db.scalars(select(Person)).all()
    me = next((p for p in people if p.is_me), None)
    roster_lines = [
        f"- {p.name} (aliases: {', '.join(p.aliases) if p.aliases else 'none'})"
        + (" — THIS IS ME" if p.is_me else "")
        for p in people
    ]
    roster = "\n".join(roster_lines) if roster_lines else "(registry is empty)"

    task_lines = [
        f'- task_id: {t.id}\n  title: {t.title}\n  owner: {t.owner or "null"}\n  quote: {t.source_quote or ""}'
        for t in tasks
    ]

    result = orchestrator.run_json_job(
        "classify",
        prompts.CLASSIFY_SYSTEM,
        prompts.classify_user(
            roster=roster,
            me_name=me.name if me else "(unknown)",
            transcript=build_transcript(meeting),
            tasks_block="\n".join(task_lines),
        ),
        ClassifyResult,
    )

    by_id = {str(t.id): t for t in tasks}
    roster_names = {p.name.lower(): p.name for p in people}
    for item in result.classifications:
        task = by_id.get(item.task_id)
        if task is None:
            continue
        # Human decisions are sticky — never overwritten by re-runs.
        if task.assignment_source == "user":
            continue
        task.assignment = item.assignment
        task.assignment_reason = item.reason
        if item.owner_normalized:
            canonical = roster_names.get(item.owner_normalized.lower())
            if canonical:
                task.owner = canonical
        task.segment_idx = _find_segment_idx(meeting, task)


def _find_segment_idx(meeting: Meeting, task: Task) -> int | None:
    """Fuzzy-match source_quote against segment texts for transcript highlighting."""
    if not task.source_quote:
        return None
    best_idx, best_score = None, 0.0
    for seg in meeting.segments:
        score = difflib.SequenceMatcher(
            None, seg.text.lower(), task.source_quote.lower()
        ).ratio()
        if score > best_score:
            best_idx, best_score = seg.idx, score
    return best_idx if best_score >= 0.4 else None
