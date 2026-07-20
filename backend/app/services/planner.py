"""Deterministic planner engine (phase4.md).

The LLM only triages (triage.py); this module places blocks with plain
rules:

1. Order: topological by dependencies, then priority, then due date.
2. Free slots: availability windows − busy blocks − existing kept blocks.
3. Place: greedy earliest-fit, 25–90 min chunks, 10-min buffers,
   max 4h deep work per day, spillover to next day.
4. Verify: tasks that can't finish before their due date → at_risk.

Replans delete only future, unpinned, still-planned blocks; completed,
in-progress, and pinned blocks never move.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import AvailabilityRule, BusyBlock, ScheduleBlock, Task

logger = logging.getLogger(__name__)


@dataclass
class PlanWarning:
    task_id: str
    title: str
    kind: str  # at_risk | no_estimate
    detail: str


def tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def replan(db: Session, now: datetime | None = None) -> list[PlanWarning]:
    """Rebuild the schedule for open 'mine' tasks. One transaction."""
    now = (now or datetime.now(tz())).astimezone(tz())
    warnings: list[PlanWarning] = []

    # Self-heal orphans: blocks whose task was completed, dropped, or handed off
    # after they were scheduled. replan only rebuilds open 'mine' tasks, so these
    # would otherwise linger in the plan forever (keep done/skipped ones as history).
    orphans = db.scalars(
        select(ScheduleBlock)
        .join(Task)
        .where(
            ScheduleBlock.status == "planned",
            ScheduleBlock.pinned.is_(False),
            or_(Task.status != "open", Task.assignment != "mine"),
        )
    ).all()
    for b in orphans:
        db.delete(b)

    tasks = list(
        db.scalars(
            select(Task)
            .options(selectinload(Task.blocks))
            .where(Task.assignment == "mine", Task.status == "open")
        )
    )

    # 1. Delete future, unpinned, still-planned blocks (kept blocks stay).
    kept_blocks: list[ScheduleBlock] = []
    for t in tasks:
        for b in list(t.blocks):
            if b.status == "planned" and not b.pinned and b.start_at > now:
                db.delete(b)
                t.blocks.remove(b)
            else:
                kept_blocks.append(b)

    # 2. Remaining minutes per task (estimate − already-kept planned/done time).
    todo: list[tuple[Task, int]] = []
    for t in tasks:
        if t.estimated_minutes is None:
            warnings.append(PlanWarning(str(t.id), t.title, "no_estimate", "Task has no time estimate"))
            continue
        kept_min = sum(
            int((b.end_at - b.start_at).total_seconds() // 60)
            for b in t.blocks
            if b.status in ("planned", "in_progress", "done")
        )
        remaining = max(0, int(t.estimated_minutes * (100 - t.progress) / 100) - kept_min)
        if remaining > 0:
            todo.append((t, remaining))

    ordered = _order_tasks(todo)

    # 3. Build free slots over the horizon and place greedily.
    slots = _free_slots(db, now, kept_blocks)
    placements: dict[str, list[tuple[datetime, datetime]]] = {}
    deep_used: dict[tuple[date, str], int] = {}  # (day, category) -> minutes placed

    for task, remaining in ordered:
        prefer_energy = _effective_energy(task)
        placed: list[tuple[datetime, datetime]] = []
        while remaining > 0:
            slot_i = _find_slot(slots, task.category, remaining, deep_used, prefer_energy)
            if slot_i is None:
                break
            s = slots[slot_i]
            day_key = (s.start.date(), task.category)
            day_left = settings.plan_deep_work_min_per_day - deep_used.get(day_key, 0)
            chunk = min(remaining, settings.plan_max_block_min, s.minutes, day_left)
            if chunk < min(settings.plan_min_block_min, remaining):
                # Slot too small to be useful; skip it for this task.
                s.skip_categories.add(task.category)
                continue
            start = s.start
            end = start + timedelta(minutes=chunk)
            placed.append((start, end))
            deep_used[day_key] = deep_used.get(day_key, 0) + chunk
            remaining -= chunk
            s.consume(end + timedelta(minutes=settings.plan_buffer_min))
        placements[str(task.id)] = placed
        if remaining > 0:
            task.at_risk = True
            warnings.append(
                PlanWarning(
                    str(task.id),
                    task.title,
                    "at_risk",
                    f"{remaining} min could not be scheduled within the {settings.plan_horizon_days}-day horizon",
                )
            )

    # 4. Write blocks + at_risk flags in the same transaction.
    for task, _ in ordered:
        blocks = placements.get(str(task.id), [])
        for start, end in blocks:
            db.add(ScheduleBlock(task_id=task.id, start_at=start, end_at=end))
        if blocks:
            last_end = max(e for _, e in blocks)
            due_risk = task.due_date is not None and last_end.date() > task.due_date
            task.at_risk = task.at_risk or due_risk
            if due_risk:
                warnings.append(
                    PlanWarning(
                        str(task.id),
                        task.title,
                        "at_risk",
                        f"Finishes {last_end.date().isoformat()}, after due date {task.due_date.isoformat()}",
                    )
                )
            if task.start_date is None:
                task.start_date = min(s for s, _ in blocks).date()
        if not task.at_risk:
            task.at_risk = False

    db.commit()
    return warnings


def _order_tasks(todo: list[tuple[Task, int]]) -> list[tuple[Task, int]]:
    """Topological by dependency titles, then priority, then due date."""
    prio_rank = {"high": 0, "medium": 1, "low": 2, None: 3}
    by_title = {t.title.lower(): (t, m) for t, m in todo}

    # Kahn-style: a task depends on another *in this set* if a dependency
    # phrase fuzzy-contains that task's title (dependencies are free text).
    def dep_keys(t: Task) -> list[str]:
        keys = []
        for dep in t.dependencies or []:
            d = str(dep).lower()
            for title in by_title:
                if title != t.title.lower() and (title in d or d in title):
                    keys.append(title)
        return keys

    remaining = dict(by_title)
    ordered: list[tuple[Task, int]] = []
    while remaining:
        ready = [
            (t, m)
            for t, m in remaining.values()
            if not any(k in remaining for k in dep_keys(t))
        ]
        if not ready:  # dependency cycle — fall back to flat ordering
            ready = list(remaining.values())
        ready.sort(key=lambda x: (prio_rank.get(x[0].priority, 3), x[0].due_date or date.max, x[0].title))
        for t, m in ready:
            ordered.append((t, m))
            remaining.pop(t.title.lower(), None)
    return ordered


def _effective_energy(task: Task) -> str:
    """Which window a task prefers: deep for heavy work, shallow for light.

    Explicit task.intensity wins; otherwise auto — high-priority or long tasks
    (>= 1h) count as heavy so they land in sharp hours by default.
    """
    intensity = task.intensity
    if intensity is None:
        heavy = task.priority == "high" or (task.estimated_minutes or 0) >= 60
        intensity = "heavy" if heavy else "light"
    return "deep" if intensity == "heavy" else "shallow"


class _Slot:
    def __init__(self, start: datetime, end: datetime, category: str, energy: str = "deep"):
        self.start = start
        self.end = end
        self.category = category
        self.energy = energy
        self.skip_categories: set[str] = set()

    @property
    def minutes(self) -> int:
        return max(0, int((self.end - self.start).total_seconds() // 60))

    def consume(self, new_start: datetime) -> None:
        self.start = min(new_start, self.end)


def _free_slots(db: Session, now: datetime, kept_blocks: list[ScheduleBlock]) -> list[_Slot]:
    rules = list(db.scalars(select(AvailabilityRule)))
    busy = list(db.scalars(select(BusyBlock)))
    zone = tz()

    slots: list[_Slot] = []
    for offset in range(settings.plan_horizon_days):
        day = (now + timedelta(days=offset)).date()
        wd = day.weekday()
        for rule in rules:
            if rule.weekday != wd:
                continue
            start = datetime.combine(day, rule.start_t, zone)
            end = datetime.combine(day, rule.end_t, zone)
            if end <= now:
                continue
            start = max(start, _ceil_to_5(now))
            windows = [(start, end)] if start < end else []
            # Subtract busy blocks (recurring by weekday, or one-off by date).
            for b in busy:
                if not ((b.weekday is not None and b.weekday == wd) or (b.date == day)):
                    continue
                b_start = datetime.combine(day, b.start_t, zone)
                b_end = datetime.combine(day, b.end_t, zone)
                windows = _subtract(windows, b_start, b_end)
            # Subtract kept schedule blocks (with buffer).
            for kb in kept_blocks:
                pad = timedelta(minutes=settings.plan_buffer_min)
                windows = _subtract(windows, kb.start_at - pad, kb.end_at + pad)
            for w_start, w_end in windows:
                if (w_end - w_start) >= timedelta(minutes=settings.plan_min_block_min):
                    slots.append(_Slot(w_start, w_end, rule.category, rule.energy))

    slots.sort(key=lambda s: s.start)
    return slots


def _slot_usable(s: _Slot, category: str, remaining: int, deep_used: dict) -> bool:
    if s.category != category or category in s.skip_categories:
        return False
    if s.minutes < min(settings.plan_min_block_min, remaining):
        return False
    if deep_used.get((s.start.date(), category), 0) >= settings.plan_deep_work_min_per_day:
        return False
    return True


def _find_slot(
    slots: list[_Slot],
    category: str,
    remaining: int,
    deep_used: dict,
    prefer_energy: str | None = None,
) -> int | None:
    """Earliest usable slot of the category, preferring the task's energy level.

    The energy preference only reorders within the earliest available day — a
    heavy task grabs a deep window over a shallow one the same day, but is never
    pushed to a later day just to find deep time (that's the planner's job to flag
    as at-risk, not to silently delay).
    """
    first_i: int | None = None
    earliest_day = None
    for i, s in enumerate(slots):
        if not _slot_usable(s, category, remaining, deep_used):
            continue
        if first_i is None:
            first_i, earliest_day = i, s.start.date()
        if s.start.date() != earliest_day:
            break  # past the earliest day — stop hunting for a preferred match
        if prefer_energy and s.energy == prefer_energy:
            return i
    return first_i


def _subtract(
    windows: list[tuple[datetime, datetime]], cut_start: datetime, cut_end: datetime
) -> list[tuple[datetime, datetime]]:
    out = []
    for start, end in windows:
        if cut_end <= start or cut_start >= end:
            out.append((start, end))
            continue
        if cut_start > start:
            out.append((start, cut_start))
        if cut_end < end:
            out.append((cut_end, end))
    return out


def _ceil_to_5(dt: datetime) -> datetime:
    minute = (dt.minute // 5 + 1) * 5
    if minute >= 60:
        return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return dt.replace(minute=minute, second=0, microsecond=0)
