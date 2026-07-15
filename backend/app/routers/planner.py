import uuid
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import AvailabilityRule, BusyBlock, ScheduleBlock, Task
from ..schemas import (
    AvailabilityRuleIn,
    AvailabilityRuleOut,
    BusyBlockIn,
    BusyBlockOut,
    DayBlock,
    PlanResponse,
    PlanWarningOut,
    ScheduleBlockOut,
    ScheduleBlockPatch,
)
from ..services import planner, triage

router = APIRouter(prefix="/api", tags=["planner"])


# --- Availability rules ---

@router.get("/availability", response_model=list[AvailabilityRuleOut])
def get_availability(db: Session = Depends(get_db)):
    return db.scalars(select(AvailabilityRule).order_by(AvailabilityRule.weekday, AvailabilityRule.start_t)).all()


@router.put("/availability", response_model=list[AvailabilityRuleOut])
def put_availability(rules: list[AvailabilityRuleIn], db: Session = Depends(get_db)):
    """Replace the full rule set atomically."""
    for r in rules:
        if r.end_t <= r.start_t:
            raise HTTPException(422, f"end must be after start ({r.weekday}: {r.start_t}–{r.end_t})")
    for existing in db.scalars(select(AvailabilityRule)).all():
        db.delete(existing)
    for r in rules:
        db.add(AvailabilityRule(**r.model_dump()))
    db.commit()
    return db.scalars(select(AvailabilityRule).order_by(AvailabilityRule.weekday, AvailabilityRule.start_t)).all()


# --- Busy blocks ---

@router.get("/busy-blocks", response_model=list[BusyBlockOut])
def list_busy(db: Session = Depends(get_db)):
    return db.scalars(select(BusyBlock).order_by(BusyBlock.weekday, BusyBlock.date, BusyBlock.start_t)).all()


@router.post("/busy-blocks", response_model=BusyBlockOut, status_code=201)
def create_busy(body: BusyBlockIn, db: Session = Depends(get_db)):
    if (body.weekday is None) == (body.date is None):
        raise HTTPException(422, "Exactly one of weekday (recurring) or date (one-off) must be set")
    if body.end_t <= body.start_t:
        raise HTTPException(422, "end must be after start")
    block = BusyBlock(**body.model_dump())
    db.add(block)
    db.commit()
    return block


@router.delete("/busy-blocks/{block_id}", status_code=204)
def delete_busy(block_id: uuid.UUID, db: Session = Depends(get_db)):
    block = db.get(BusyBlock, block_id)
    if not block:
        raise HTTPException(404, "Busy block not found")
    db.delete(block)
    db.commit()


# --- Planning ---

@router.post("/plan", response_model=PlanResponse)
def run_plan(db: Session = Depends(get_db)):
    """Triage under-specified 'mine' tasks, then replan the schedule.

    replan() orders by priority and due date, so a task missing either is a task
    the planner has to guess about — triage fills both, plus the estimate it
    needs to size the block.
    """
    tasks = list(db.scalars(select(Task).where(Task.assignment == "mine", Task.status == "open")))
    estimate_error = None
    try:
        triage.triage_tasks(db, tasks)
    except Exception as exc:  # planning still proceeds with whatever estimates exist
        db.rollback()
        estimate_error = str(exc)
    warnings = planner.replan(db)
    resp = PlanResponse(
        warnings=[PlanWarningOut(**w.__dict__) for w in warnings],
        today=_day_blocks(db, datetime.now(planner.tz()).date()),
    )
    if estimate_error:
        resp.warnings.insert(
            0, PlanWarningOut(task_id="", title="estimation", kind="estimate_failed", detail=estimate_error[:300])
        )
    return resp


@router.get("/plan/today", response_model=list[DayBlock])
def plan_today(db: Session = Depends(get_db)):
    return _day_blocks(db, datetime.now(planner.tz()).date())


@router.get("/plan/range", response_model=list[DayBlock])
def plan_range(frm: str, to: str, db: Session = Depends(get_db)):
    try:
        start = datetime.fromisoformat(frm).date()
        end = datetime.fromisoformat(to).date()
    except ValueError:
        raise HTTPException(422, "frm/to must be ISO dates")
    zone = planner.tz()
    return _blocks_between(
        db,
        datetime.combine(start, time.min, zone),
        datetime.combine(end + timedelta(days=1), time.min, zone),
    )


@router.patch("/schedule-blocks/{block_id}", response_model=ScheduleBlockOut)
def patch_block(block_id: uuid.UUID, patch: ScheduleBlockPatch, db: Session = Depends(get_db)):
    block = db.get(ScheduleBlock, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    fields = patch.model_dump(exclude_unset=True)
    if "start_at" in fields or "end_at" in fields:
        block.pinned = True  # manual reschedule: replans must not move it
    for k, v in fields.items():
        if v is not None:
            setattr(block, k, v)
    if block.end_at <= block.start_at:
        db.rollback()
        raise HTTPException(422, "end must be after start")
    db.commit()
    return block


def _day_blocks(db: Session, day) -> list[DayBlock]:
    zone = planner.tz()
    start = datetime.combine(day, time.min, zone)
    return _blocks_between(db, start, start + timedelta(days=1))


def _blocks_between(db: Session, start: datetime, end: datetime) -> list[DayBlock]:
    blocks = db.scalars(
        select(ScheduleBlock)
        .options(selectinload(ScheduleBlock.task))
        .where(ScheduleBlock.start_at >= start, ScheduleBlock.start_at < end)
        .order_by(ScheduleBlock.start_at)
    ).all()
    return [
        DayBlock(
            id=b.id,
            task_id=b.task_id,
            task_title=b.task.title,
            category=b.task.category,
            priority=b.task.priority,
            start_at=b.start_at,
            end_at=b.end_at,
            status=b.status,
            pinned=b.pinned,
            at_risk=b.task.at_risk,
        )
        for b in blocks
    ]
