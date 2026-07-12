"""APScheduler jobs — Phase 4c morning routine.

Every morning at MORNING_PLAN_TIME: replan the day and post a "here's your
day" summary as an assistant message in chat (Phase 5 upgrades this into the
channel-based notification service).
"""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import ChatMessage, ScheduleBlock, Task
from . import planner

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    hour, minute = map(int, settings.morning_plan_time.split(":"))
    _scheduler = BackgroundScheduler(timezone=settings.timezone)
    _scheduler.add_job(morning_routine, CronTrigger(hour=hour, minute=minute), id="morning")
    _scheduler.start()
    logger.info("Morning routine scheduled daily at %s %s", settings.morning_plan_time, settings.timezone)


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def morning_routine() -> None:
    db = SessionLocal()
    try:
        warnings = planner.replan(db)

        now = datetime.now(planner.tz())
        today = now.date()
        blocks = db.scalars(
            select(ScheduleBlock)
            .where(ScheduleBlock.start_at >= now.replace(hour=0, minute=0, second=0, microsecond=0))
            .order_by(ScheduleBlock.start_at)
        ).all()
        todays = [b for b in blocks if b.start_at.astimezone(planner.tz()).date() == today]
        overdue = db.scalars(
            select(Task).where(Task.assignment == "mine", Task.status == "open", Task.due_date < today)
        ).all()

        lines = [f"Good morning! Here's your {today.strftime('%A')}:"]
        if todays:
            for b in todays:
                s = b.start_at.astimezone(planner.tz()).strftime("%H:%M")
                e = b.end_at.astimezone(planner.tz()).strftime("%H:%M")
                lines.append(f"• {s}–{e} {b.task.title}")
        else:
            lines.append("• Nothing scheduled today.")
        at_risk = [w for w in warnings if w.kind == "at_risk"]
        if at_risk:
            lines.append(f"⚠ {len(at_risk)} task(s) at risk: " + "; ".join(w.title for w in at_risk))
        if overdue:
            lines.append(f"⏰ {len(overdue)} overdue: " + "; ".join(t.title for t in overdue))

        db.add(ChatMessage(role="assistant", content="\n".join(lines)))
        db.commit()
    except Exception:
        logger.exception("Morning routine failed")
    finally:
        db.close()
