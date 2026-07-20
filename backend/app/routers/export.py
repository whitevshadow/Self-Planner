"""Full-data export — a one-click backup of everything the app knows.

Bundles structured JSON (for re-import / inspection) plus human-readable
Markdown per meeting (so an archive is useful even without the app). Audio is
deliberately excluded to keep the download light — the JSON keeps each
`audio_key`, and the README documents the `mc`/`pg_dump` path for the heavy copy.
"""
import io
import json
import re
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..models import (
    AvailabilityRule,
    BusyBlock,
    ChatMessage,
    Meeting,
    Person,
    ScheduleBlock,
    Task,
)

router = APIRouter(prefix="/api", tags=["export"])


def _json(obj) -> str:
    # default=str turns UUID / date / datetime into ISO-ish strings losslessly.
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


def _row(model, cols: list[str]) -> dict:
    return {c: getattr(model, c) for c in cols}


_MEETING_COLS = [
    "id", "title", "filename", "audio_key", "duration_sec", "status", "error",
    "diarize_status", "speaker_map", "summary", "decisions", "notes",
    "extract_status", "extract_error", "created_at",
]
_SEGMENT_COLS = ["id", "idx", "start_sec", "end_sec", "text", "speaker", "speaker_raw"]
_TASK_COLS = [
    "id", "meeting_id", "title", "owner", "due_date", "priority", "dependencies",
    "source_quote", "status", "edited", "assignment", "assignment_reason",
    "assignment_source", "segment_idx", "category", "estimated_minutes",
    "estimate_source", "steps", "progress", "start_date", "at_risk", "created_at",
]
_BLOCK_COLS = ["id", "task_id", "start_at", "end_at", "status", "pinned", "gcal_event_id"]


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^\w\- ]", "", text or "").strip().replace(" ", "-").lower()
    return (s[:60] or fallback)


def _meeting_markdown(m: Meeting, tasks: list[Task]) -> str:
    lines = [f"# {m.title}", ""]
    lines.append(f"- **Date:** {m.created_at.date().isoformat()}")
    if m.duration_sec:
        lines.append(f"- **Duration:** {round(m.duration_sec / 60)} min")
    lines.append(f"- **Source file:** {m.filename}")
    lines.append("")

    if m.summary:
        lines += ["## Summary", "", m.summary, ""]
    if m.decisions:
        lines += ["## Decisions", ""] + [f"- {d}" for d in m.decisions] + [""]

    mine = [t for t in tasks if t.assignment == "mine"]
    if mine:
        lines += ["## My tasks", ""]
        for t in mine:
            due = f" — due {t.due_date.isoformat()}" if t.due_date else ""
            prio = f" [{t.priority}]" if t.priority else ""
            lines.append(f"- {t.title}{prio}{due}")
        lines.append("")

    if m.notes:
        lines += ["## Meeting notes", "", m.notes, ""]

    if m.segments:
        lines += ["## Transcript", ""]
        for s in m.segments:
            mm, ss = divmod(int(s.start_sec), 60)
            who = s.speaker or s.speaker_raw or ""
            who = f"**{who}:** " if who else ""
            lines.append(f"`[{mm:02d}:{ss:02d}]` {who}{s.text}")
        lines.append("")

    return "\n".join(lines)


@router.get("/export")
def export_all(db: Session = Depends(get_db)):
    """Stream a .zip backup of every meeting, task, plan, and setting."""
    meetings = list(
        db.scalars(
            select(Meeting)
            .options(selectinload(Meeting.segments), selectinload(Meeting.tasks))
            .where(Meeting.title != "__chat__")  # skip the synthetic chat container
            .order_by(Meeting.created_at)
        )
    )
    tasks = list(db.scalars(select(Task).order_by(Task.created_at)))
    blocks = list(db.scalars(select(ScheduleBlock).order_by(ScheduleBlock.start_at)))
    rules = list(db.scalars(select(AvailabilityRule).order_by(AvailabilityRule.weekday)))
    busy = list(db.scalars(select(BusyBlock)))
    people = list(db.scalars(select(Person).order_by(Person.name)))
    chat = list(db.scalars(select(ChatMessage).order_by(ChatMessage.created_at)))

    now = datetime.now()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # --- structured JSON ---
        z.writestr(
            "data/meetings.json",
            _json([
                {**_row(m, _MEETING_COLS), "segments": [_row(s, _SEGMENT_COLS) for s in m.segments]}
                for m in meetings
            ]),
        )
        z.writestr("data/tasks.json", _json([_row(t, _TASK_COLS) for t in tasks]))
        z.writestr(
            "data/plan.json",
            _json({
                "schedule_blocks": [_row(b, _BLOCK_COLS) for b in blocks],
                "availability_rules": [_row(r, ["id", "category", "weekday", "start_t", "end_t"]) for r in rules],
                "busy_blocks": [_row(b, ["id", "label", "weekday", "date", "start_t", "end_t", "source"]) for b in busy],
            }),
        )
        z.writestr("data/people.json", _json([_row(p, ["id", "name", "aliases", "is_me"]) for p in people]))
        z.writestr("data/chat.json", _json([_row(c, ["id", "role", "content", "tool_calls", "created_at"]) for c in chat]))

        # --- human-readable Markdown per meeting ---
        tasks_by_meeting: dict = {}
        for t in tasks:
            tasks_by_meeting.setdefault(t.meeting_id, []).append(t)
        used: set[str] = set()
        for m in meetings:
            name = _slug(m.title, str(m.id)[:8])
            fname = f"meetings/{name}-{str(m.id)[:8]}.md"
            while fname in used:  # unique even if two meetings share a title
                fname = f"meetings/{name}-{str(m.id)[:12]}.md"
            used.add(fname)
            z.writestr(fname, _meeting_markdown(m, tasks_by_meeting.get(m.id, [])))

        z.writestr(
            "README.txt",
            "Self Planner export\n"
            f"Created: {now.isoformat(timespec='seconds')}\n\n"
            f"Meetings: {len(meetings)}\nTasks: {len(tasks)}\n"
            f"Schedule blocks: {len(blocks)}\nPeople: {len(people)}\n\n"
            "Contents:\n"
            "  data/*.json     — full structured backup (meetings+segments, tasks, plan, people, chat)\n"
            "  meetings/*.md    — human-readable summary, decisions, tasks and transcript per meeting\n\n"
            "Audio is NOT included here (kept light). To back up the raw recordings and the\n"
            "database itself:\n"
            "  Audio:    mc cp --recursive local/meetings-audio ./audio-backup   (MinIO client)\n"
            "  Database: pg_dump self_planner > self_planner.sql\n",
        )

    buf.seek(0)
    fname = f"self-planner-export-{now.strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
