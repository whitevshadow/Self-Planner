"""Chatbot agent (LLM job: chat) with a JSON tool protocol.

The model replies with exactly one JSON object per turn:
  {"reply": "..."}                              — final answer / clarifying question
  {"tool": "<name>", "args": {...}}             — invoke a tool, get result, continue

Tool arguments are Pydantic-validated before execution (structure over vibes);
the agent asks ONE concise clarifying question when required details are missing.
"""
from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import ChatMessage, ScheduleBlock, Task
from . import orchestrator, planner

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 4


# --- Tool argument schemas ---

class AddTaskArgs(BaseModel):
    title: str = Field(min_length=1)
    category: str = Field(pattern="^(work|personal)$")
    due_date: date | None = None
    priority: str | None = Field(default=None, pattern="^(high|medium|low)$")
    estimated_minutes: int | None = Field(default=None, ge=5, le=960)


class UpdateTaskArgs(BaseModel):
    task_id: str
    title: str | None = None
    due_date: date | None = None
    priority: str | None = Field(default=None, pattern="^(high|medium|low)$")
    status: str | None = Field(default=None, pattern="^(open|done|dropped)$")
    progress: int | None = Field(default=None, ge=0, le=100)
    estimated_minutes: int | None = Field(default=None, ge=5, le=960)


class QueryArgs(BaseModel):
    what: str = Field(pattern="^(today|tomorrow|overdue|open_tasks|week)$")


class EmptyArgs(BaseModel):
    pass


SYSTEM_PROMPT = """You are Self Planner's assistant for Anish. Today is {today} ({weekday}), timezone {tz}.

Respond with ONLY one JSON object per turn — no prose outside JSON:
  {{"reply": "<message to Anish>"}}          — to answer or ask ONE clarifying question
  {{"tool": "<tool_name>", "args": {{...}}}}   — to act; you'll receive the result and continue

Tools:
- add_task: args {{title, category: "work"|"personal", due_date: "YYYY-MM-DD"|null, priority: "high"|"medium"|"low"|null, estimated_minutes: int|null}}
  RULE: before calling, you MUST know title + category + (due date or explicitly none).
  If anything is missing or ambiguous, ask ONE concise question instead of guessing.
- update_task: args {{task_id, ...fields to change (status "done" completes a task, progress 0-100)}}
- query: args {{what: "today"|"tomorrow"|"overdue"|"open_tasks"|"week"}} — schedule/tasks facts
- replan: args {{}} — rebuild the schedule after changes

Rules:
- Resolve relative dates against today's date. "Thursday" = the next Thursday.
- To act on a task by name, first use query open_tasks to find its task_id.
- After add_task or update_task that changes scope, call replan, then confirm briefly to Anish.
- Keep replies short and concrete. Never invent tasks or schedule facts — query first.
"""


def handle_message(db: Session, user_text: str) -> list[ChatMessage]:
    """Process one user message; returns new messages (user, tool notes, assistant)."""
    new_messages: list[ChatMessage] = []

    def save(role: str, content: str, tool_calls=None) -> ChatMessage:
        msg = ChatMessage(role=role, content=content, tool_calls=tool_calls)
        db.add(msg)
        db.commit()
        new_messages.append(msg)
        return msg

    save("user", user_text)

    now = datetime.now(planner.tz())
    system = SYSTEM_PROMPT.format(
        today=now.date().isoformat(), weekday=now.strftime("%A"), tz=settings.timezone
    )

    # Conversation context: last 20 messages.
    history = list(
        db.scalars(select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(20))
    )[::-1]
    messages = [{"role": "system", "content": system}] + [
        {"role": m.role if m.role != "tool" else "user",
         "content": m.content if m.role != "tool" else f"[tool result] {m.content}"}
        for m in history
    ]

    client = orchestrator._get_client()
    model = orchestrator._model_for_job("chat")

    tools_ran = False
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0.2, max_tokens=800
            )
        except Exception as exc:
            # If tools already executed, surface partial success instead of an
            # error — a retried request must not re-run the same actions.
            if tools_ran:
                save("assistant", "I applied the actions above, but lost the connection while wrapping up. Ask me to continue if something is missing.")
                return new_messages
            raise exc
        raw = resp.choices[0].message.content or ""
        try:
            action = orchestrator._extract_json(raw)
        except Exception:
            save("assistant", raw.strip() or "Sorry, I had trouble forming a response — try again.")
            return new_messages

        if "reply" in action:
            save("assistant", str(action["reply"]))
            return new_messages

        tool = action.get("tool", "")
        args = action.get("args", {}) or {}
        try:
            result = _run_tool(db, tool, args)
        except (ValidationError, ValueError) as exc:
            result = f"error: {exc}"
        tools_ran = True
        save("tool", json.dumps(result) if not isinstance(result, str) else result,
             tool_calls=[{"tool": tool, "args": args}])
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"[tool result] {json.dumps(result, default=str)[:3000]}"})

    save("assistant", "I hit my tool-call limit for this message — the actions above were applied.")
    return new_messages


def _run_tool(db: Session, tool: str, args: dict):
    if tool == "add_task":
        a = AddTaskArgs.model_validate(args)
        # Idempotency: an identical open task means a retried request — reuse it.
        existing = db.scalar(
            select(Task).where(
                Task.title.ilike(a.title), Task.status == "open", Task.due_date == a.due_date
            )
        )
        if existing:
            return {"created_task_id": str(existing.id), "title": existing.title, "note": "already existed"}
        task = Task(
            meeting_id=_chat_meeting_id(db),
            title=a.title,
            category=a.category,
            due_date=a.due_date,
            priority=a.priority,
            estimated_minutes=a.estimated_minutes,
            estimate_source="user" if a.estimated_minutes else "llm",
            assignment="mine",
            assignment_source="user",
            assignment_reason="Added via chat",
            edited=True,
        )
        db.add(task)
        db.commit()
        return {"created_task_id": str(task.id), "title": task.title}

    if tool == "update_task":
        a = UpdateTaskArgs.model_validate(args)
        task = db.get(Task, uuid_mod.UUID(a.task_id))
        if not task:
            return f"error: no task with id {a.task_id}"
        for field in ("title", "due_date", "priority", "status", "progress", "estimated_minutes"):
            v = getattr(a, field)
            if v is not None:
                setattr(task, field, v)
        task.edited = True
        if a.estimated_minutes is not None:
            task.estimate_source = "user"
        db.commit()
        return {"updated": str(task.id), "status": task.status, "progress": task.progress}

    if tool == "query":
        a = QueryArgs.model_validate(args)
        return _query(db, a.what)

    if tool == "replan":
        EmptyArgs.model_validate(args)
        warnings = planner.replan(db)
        return {"replanned": True, "warnings": [w.detail for w in warnings]}

    return f"error: unknown tool '{tool}'"


def _query(db: Session, what: str):
    now = datetime.now(planner.tz())
    today = now.date()

    if what == "open_tasks":
        tasks = db.scalars(
            select(Task).where(Task.assignment == "mine", Task.status == "open")
        ).all()
        return [
            {"task_id": str(t.id), "title": t.title, "due": str(t.due_date), "priority": t.priority,
             "category": t.category, "estimated_minutes": t.estimated_minutes, "progress": t.progress}
            for t in tasks
        ]

    if what == "overdue":
        tasks = db.scalars(
            select(Task).where(
                Task.assignment == "mine", Task.status == "open", Task.due_date < today
            )
        ).all()
        return [{"task_id": str(t.id), "title": t.title, "due": str(t.due_date)} for t in tasks]

    day_start = {"today": today, "tomorrow": today + timedelta(days=1), "week": today}.get(what, today)
    span = 7 if what == "week" else 1
    from datetime import time as dt_time

    start = datetime.combine(day_start, dt_time.min, planner.tz())
    blocks = db.scalars(
        select(ScheduleBlock)
        .where(ScheduleBlock.start_at >= start, ScheduleBlock.start_at < start + timedelta(days=span))
        .order_by(ScheduleBlock.start_at)
    ).all()
    return [
        {"start": b.start_at.astimezone(planner.tz()).strftime("%a %H:%M"),
         "end": b.end_at.astimezone(planner.tz()).strftime("%H:%M"),
         "task": b.task.title, "status": b.status}
        for b in blocks
    ]


def _chat_meeting_id(db: Session):
    """Chat-created tasks hang off a synthetic 'Chat' meeting (tasks require one)."""
    from ..models import Meeting

    meeting = db.scalar(select(Meeting).where(Meeting.title == "__chat__"))
    if meeting is None:
        meeting = Meeting(
            title="__chat__", filename="chat", audio_key="none", status="done",
            extract_status="done", diarize_status="skipped",
        )
        db.add(meeting)
        db.commit()
    return meeting.id
