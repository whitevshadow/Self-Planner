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
    BlockExtendIn,
    BusyBlockIn,
    BusyBlockOut,
    DayBlock,
    NowBlock,
    NowView,
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


@router.post("/plan/replan", response_model=PlanResponse)
def replan_today(db: Session = Depends(get_db)):
    """Deterministic repack from *now* — no triage, no LLM.

    For when the day drifts (a task ran long): reflows future, unpinned blocks
    around what's already happened. Instant, unlike /plan which re-triages first.
    """
    warnings = planner.replan(db)
    return PlanResponse(
        warnings=[PlanWarningOut(**w.__dict__) for w in warnings],
        today=_day_blocks(db, datetime.now(planner.tz()).date()),
    )


@router.get("/plan/now", response_model=NowView)
def plan_now(db: Session = Depends(get_db)):
    """What am I doing right now, and what's next — pure SQL, no LLM."""
    now = datetime.now(planner.tz())
    upcoming = db.scalars(
        select(ScheduleBlock)
        .options(selectinload(ScheduleBlock.task))
        .where(ScheduleBlock.end_at > now, ScheduleBlock.status.in_(("planned", "in_progress")))
        .order_by(ScheduleBlock.start_at)
    ).all()

    current = next((b for b in upcoming if b.start_at <= now < b.end_at), None)
    nxt = next((b for b in upcoming if b.start_at > now), None)

    free_minutes = None
    # Only meaningful as a "free for N min" gap when the next block is later today;
    # a block tomorrow would otherwise report hundreds of idle minutes.
    if current is None and nxt is not None and nxt.start_at.astimezone(planner.tz()).date() == now.date():
        free_minutes = max(0, int((nxt.start_at - now).total_seconds() // 60))

    return NowView(
        now=now,
        current=_now_block(current),
        next=_now_block(nxt),
        free_minutes=free_minutes,
    )


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


@router.post("/schedule-blocks/{block_id}/extend", response_model=PlanResponse)
def extend_block(block_id: uuid.UUID, body: BlockExtendIn, db: Session = Depends(get_db)):
    """"Still going" — grow the active block by N minutes and reflow the rest of
    the day around it. Pinned so the follow-up replan keeps the longer block."""
    block = db.get(ScheduleBlock, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    if block.status in ("done", "skipped"):
        raise HTTPException(409, "Block is already finished")
    block.end_at = block.end_at + timedelta(minutes=body.minutes)
    block.pinned = True
    if block.status == "planned":
        block.status = "in_progress"
    db.commit()
    warnings = planner.replan(db)
    return PlanResponse(
        warnings=[PlanWarningOut(**w.__dict__) for w in warnings],
        today=_day_blocks(db, datetime.now(planner.tz()).date()),
    )


@router.post("/schedule-blocks/{block_id}/carry-over", response_model=PlanResponse)
def carry_over_block(block_id: uuid.UUID, db: Session = Depends(get_db)):
    """"Didn't finish" — close the active block now and let the remaining
    estimate reschedule into the next free slot."""
    block = db.get(ScheduleBlock, block_id)
    if not block:
        raise HTTPException(404, "Block not found")
    if block.status in ("done", "skipped"):
        raise HTTPException(409, "Block is already finished")
    now = datetime.now(planner.tz())
    # Shrink to actual time spent so the leftover estimate is what gets replanned.
    block.end_at = max(block.start_at + timedelta(minutes=1), min(block.end_at, now))
    block.status = "done"
    db.commit()
    warnings = planner.replan(db)
    return PlanResponse(
        warnings=[PlanWarningOut(**w.__dict__) for w in warnings],
        today=_day_blocks(db, datetime.now(planner.tz()).date()),
    )


def _now_block(b: ScheduleBlock | None) -> NowBlock | None:
    if b is None:
        return None
    return NowBlock(
        id=b.id,
        task_id=b.task_id,
        task_title=b.task.title,
        category=b.task.category,
        priority=b.task.priority,
        start_at=b.start_at,
        end_at=b.end_at,
        status=b.status,
    )


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
