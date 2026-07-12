"""Time estimation (LLM job 4): unestimated tasks → {estimated_minutes, steps[]}.

User overrides (estimate_source='user') are never re-estimated.
The LLM only estimates — it never places blocks (planner.py is deterministic).
"""
import logging

from sqlalchemy.orm import Session

from ..models import Task
from ..schemas import EstimateResult
from . import orchestrator, prompts

logger = logging.getLogger(__name__)


def estimate_tasks(db: Session, tasks: list[Task]) -> None:
    """Fill estimated_minutes/steps for tasks lacking them. Commits on success."""
    pending = [t for t in tasks if t.estimated_minutes is None and t.estimate_source != "user"]
    if not pending:
        return

    task_lines = [
        f"- task_id: {t.id}\n  title: {t.title}\n  quote: {t.source_quote or ''}\n  category: {t.category}"
        for t in pending
    ]
    result = orchestrator.run_json_job(
        "plan",
        prompts.ESTIMATE_SYSTEM,
        "Tasks to estimate:\n" + "\n".join(task_lines),
        EstimateResult,
    )

    by_id = {str(t.id): t for t in pending}
    for item in result.estimates:
        task = by_id.get(item.task_id)
        if task is None or task.estimate_source == "user":
            continue
        task.estimated_minutes = item.estimated_minutes
        task.steps = item.steps
    db.commit()
