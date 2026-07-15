import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Person, Task
from ..schemas import AssignMineIn, TaskOut, TaskUpdate
from ..services import triage

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
def list_tasks(
    owner: str | None = None,
    status: str | None = None,
    assignment: str | None = None,
    db: Session = Depends(get_db),
):
    q = select(Task).order_by(Task.due_date.asc().nulls_last(), Task.created_at.asc())
    if owner:
        q = q.where(Task.owner.ilike(owner))
    if status:
        q = q.where(Task.status == status)
    if assignment:
        q = q.where(Task.assignment == assignment)
    return db.scalars(q).all()


@router.post("/{task_id}/confirm", response_model=TaskOut)
def confirm_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    """Maybe-mine inbox: confirm → mine. User decision, never overwritten by re-runs."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.assignment = "mine"
    task.assignment_source = "user"
    db.commit()
    return task


@router.post("/{task_id}/dismiss", response_model=TaskOut)
def dismiss_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    """Maybe-mine inbox: dismiss → others. User decision, never overwritten by re-runs."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.assignment = "others"
    task.assignment_source = "user"
    db.commit()
    return task


@router.post("/assign-mine", response_model=list[TaskOut])
def assign_mine(
    body: AssignMineIn, background: BackgroundTasks, db: Session = Depends(get_db)
):
    """Take ownership of tasks picked by hand (the meeting-page checkboxes).

    Ownership is committed and returned immediately; triage (priority, duration,
    start date, deadline) fills in behind it, because the LLM gateway hangs often
    enough that waiting on it would freeze the UI for minutes. The client polls
    for the enriched fields. Marked edited so a later re-extract cannot hand
    these tasks back to whoever the transcript named.
    """
    tasks = db.scalars(select(Task).where(Task.id.in_(body.task_ids))).all()
    missing = set(body.task_ids) - {t.id for t in tasks}
    if missing:
        raise HTTPException(404, f"Unknown task ids: {', '.join(str(m) for m in missing)}")

    me = db.scalar(select(Person).where(Person.is_me))
    if me is None:
        raise HTTPException(422, "No 'me' person configured — set one in Settings → People")

    for task in tasks:
        task.owner = me.name
        task.assignment = "mine"
        task.assignment_reason = "You assigned this to yourself"
        task.assignment_source = "user"
        task.edited = True
    db.commit()

    background.add_task(triage.triage_task_ids, list(body.task_ids))
    return tasks


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: uuid.UUID, patch: TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        return task
    for key, value in fields.items():
        setattr(task, key, value)
    task.edited = True  # user edits survive re-extraction
    if "estimated_minutes" in fields:
        task.estimate_source = "user"  # never re-estimated
    db.commit()
    return task


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    db.delete(task)
    db.commit()
