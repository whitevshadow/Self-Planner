"""Task triage (LLM job 6): priority + duration + start date + deadline.

Runs when a task becomes mine — either because the classifier said so, or
because I ticked it on the meeting page. Routed to LLM_MODEL_TRIAGE (a bigger
model than extraction: this job does date arithmetic and effort sizing, which
the 20b model gets wrong often enough to matter).

Only ever FILLS BLANKS. A priority or deadline that came out of the transcript,
and any value the user set by hand, is left exactly as it is.
"""
import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Task
from ..schemas import TriageResult
from . import orchestrator, prompts

logger = logging.getLogger(__name__)

# One LLM call per group. Small enough that the JSON for every task in the
# group fits comfortably inside the job's max_tokens budget.
BATCH_SIZE = 20


def needs_triage(task: Task) -> bool:
    return (
        task.priority is None
        or task.due_date is None
        or task.start_date is None
        or (task.estimated_minutes is None and task.estimate_source != "user")
    )


def triage_task_ids(task_ids: list[uuid.UUID]) -> None:
    """Background entry point: fresh session (the request's is gone by run time).

    The gateway hangs often enough that triage must never sit in the request
    path — the caller has already committed the assignment, so a failure here
    just leaves the tasks unenriched until the next run.
    """
    db = SessionLocal()
    try:
        tasks = db.scalars(select(Task).where(Task.id.in_(task_ids))).all()
        triage_tasks(db, list(tasks))
    except Exception:
        db.rollback()
        logger.exception("Background triage failed for tasks %s", task_ids)
    finally:
        db.close()


def triage_tasks(db: Session, tasks: list[Task]) -> int:
    """Fill missing priority/estimate/start/due on `tasks`. Commits on success.

    Returns the number of tasks the LLM actually updated. Raises if the LLM job
    fails — callers decide whether that is fatal (it usually is not).
    """
    pending = [t for t in tasks if t.status == "open" and needs_triage(t)]
    if not pending:
        return 0

    today = date.today()
    updated = 0
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        result = orchestrator.run_json_job(
            "triage",
            prompts.TRIAGE_SYSTEM,
            prompts.triage_user(today.isoformat(), today.strftime("%A"), _task_lines(batch)),
            TriageResult,
        )
        by_id = {str(t.id): t for t in batch}
        for item in result.triages:
            task = by_id.get(item.task_id)
            if task is None:
                logger.warning("Triage returned unknown task_id %s", item.task_id)
                continue
            if _apply(task, item):
                updated += 1

    db.commit()
    return updated


def _apply(task: Task, item) -> bool:
    """Write only the fields that are still blank. Returns True if anything changed."""
    changed = False

    if task.priority is None:
        task.priority = item.priority
        changed = True

    if task.estimated_minutes is None and task.estimate_source != "user":
        task.estimated_minutes = item.estimated_minutes
        if item.steps:
            task.steps = item.steps
        changed = True

    # A due date must not land before the start date, whichever of the two the
    # model supplied — the planner orders blocks by these and would produce an
    # impossible schedule.
    due = item.due_date if task.due_date is None else task.due_date
    start = item.start_date if task.start_date is None else task.start_date
    if start and due and start > due:
        start = due

    if task.due_date is None and due is not None:
        task.due_date = due
        changed = True
    if task.start_date is None and start is not None:
        task.start_date = start
        changed = True

    return changed


def _task_lines(tasks: list[Task]) -> str:
    lines = []
    for t in tasks:
        line = (
            f"- task_id: {t.id}\n"
            f"  title: {t.title}\n"
            f"  category: {t.category}\n"
            f"  quote: {t.source_quote or '(none)'}\n"
            f"  current priority: {t.priority or 'none — you decide'}\n"
            f"  current due_date: {t.due_date.isoformat() if t.due_date else 'none — you decide'}"
        )
        if t.dependencies:
            line += f"\n  waits on: {', '.join(t.dependencies)}"
        lines.append(line)
    return "\n".join(lines)
