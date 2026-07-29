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

MAX_TOOL_ROUNDS = 6
MAX_TASKS_PER_BATCH = 50


# --- Tool argument schemas ---

class AddTaskArgs(BaseModel):
    title: str = Field(min_length=1)
    category: str = Field(pattern="^(work|personal)$")
    due_date: date | None = None
    priority: str | None = Field(default=None, pattern="^(high|medium|low)$")
    estimated_minutes: int | None = Field(default=None, ge=5, le=960)


class AddTasksArgs(BaseModel):
    tasks: list[AddTaskArgs] = Field(min_length=1, max_length=MAX_TASKS_PER_BATCH)


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
- add_tasks: args {{tasks: [ {{...same fields as add_task}}, ... ]}} — add MANY tasks in ONE call.
  ALWAYS prefer this over repeated add_task when adding two or more tasks at once.
- update_task: args {{task_id, ...fields to change (status "done" completes a task, progress 0-100)}}
- query: args {{what: "today"|"tomorrow"|"overdue"|"open_tasks"|"week"}} — schedule/tasks facts
- replan: args {{}} — rebuild the schedule after changes

Rules:
- Resolve relative dates against today's date. "Thursday" = the next Thursday.
- To act on a task by name, first use query open_tasks to find its task_id.
- After add_task or update_task that changes scope, call replan, then confirm briefly to Anish.
- Keep replies short and concrete. Never invent tasks or schedule facts — query first.
"""


# Human-readable labels for the live step timeline. The UI shows these while a
# tool is running, so they are phrased as work-in-progress, not as past tense.
TOOL_RUNNING_LABEL = {
    "add_task": "Adding the task",
    "add_tasks": "Adding tasks",
    "update_task": "Updating the task",
    "query": "Checking your schedule",
    "replan": "Replanning your schedule",
}

TOOL_DONE_LABEL = {
    "add_task": "Task added",
    "add_tasks": "Tasks added",
    "update_task": "Task updated",
    "query": "Checked your schedule",
    "replan": "Schedule replanned",
}


def handle_message(db: Session, user_text: str) -> list[ChatMessage]:
    """Process one user message; returns new messages (user, tool notes, assistant).

    Non-streaming wrapper around :func:`stream_message` — used by the plain
    POST /api/chat route and the voice flow, which both want the whole turn at
    once. The agent logic lives in the generator so there is exactly one loop.
    """
    messages: list[ChatMessage] = []
    for event in stream_message(db, user_text):
        if event["type"] == "message":
            messages.append(event["_obj"])
    return messages


def stream_message(db: Session, user_text: str):
    """Run one turn, yielding events as they happen.

    Event types:
      {"type":"message","role":...,"content":...,"tool_calls":...}  a persisted message
      {"type":"step","key":n,"tool":...,"label":...,"status":"running"}
      {"type":"step","key":n,"tool":...,"label":...,"status":"done"|"error","detail":...}
      {"type":"tasks","tasks":[{id,title,due_date,priority,category}]}
      {"type":"done"}

    Each event carries a private "_obj" for in-process callers; the SSE layer
    drops it before serialising.
    """
    step_key = 0

    def save(role: str, content: str, tool_calls=None) -> ChatMessage:
        msg = ChatMessage(role=role, content=content, tool_calls=tool_calls)
        db.add(msg)
        db.commit()
        return msg

    def emit(msg: ChatMessage) -> dict:
        return {
            "type": "message",
            "id": str(msg.id),
            "role": msg.role,
            "content": msg.content,
            "tool_calls": msg.tool_calls,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "_obj": msg,
        }

    yield emit(save("user", user_text))

    now = datetime.now(planner.tz())
    system = SYSTEM_PROMPT.format(
        today=now.date().isoformat(), weekday=now.strftime("%A"), tz=settings.timezone
    )

    # Conversation context: last 20 messages. A past tool call is replayed as the
    # assistant action that caused it plus the result, so the model keeps a coherent
    # picture of what it already did across turns (not just a dangling result).
    history = list(
        db.scalars(select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(20))
    )[::-1]
    messages: list[dict] = [{"role": "system", "content": system}]
    for m in history:
        if m.role == "tool":
            call = (m.tool_calls or [{}])[0]
            messages.append({"role": "assistant", "content": json.dumps(
                {"tool": call.get("tool"), "args": call.get("args", {})})})
            messages.append({"role": "user", "content": f"[tool result] {m.content}"})
        else:
            messages.append({"role": m.role, "content": m.content})

    client = orchestrator._get_client()
    model = orchestrator._model_for_job("chat")

    # Reasoning models (gpt-oss) need the effort param routed through the gateway,
    # and hidden reasoning tokens count against max_tokens — a tight cap yields empty
    # content with finish_reason="length". Mirror orchestrator.run_json_job here.
    extra_body: dict = {}
    if settings.llm_reasoning_effort not in ("", "none") and "gpt-oss" in model:
        extra_body["reasoning_effort"] = settings.llm_reasoning_effort
        extra_body["allowed_openai_params"] = ["reasoning_effort"]

    tools_ran = False
    max_tokens = orchestrator._max_tokens_for_job("chat")

    def _next_action() -> dict | None:
        """One model turn → parsed JSON action, or None if unrecoverable.

        Retries on truncation (doubling the budget) and once on unparseable JSON,
        feeding the parse error back so the model can correct itself — the same
        self-healing run_json_job does, which the old chat loop lacked.
        """
        nonlocal max_tokens
        for attempt in range(3):
            try:
                resp = orchestrator._create_with_retry(
                    client, "chat", model=model, messages=messages,
                    temperature=0.2, max_tokens=max_tokens, extra_body=extra_body,
                )
            except Exception:
                if tools_ran:  # partial success — never re-run applied actions
                    return None
                raise
            choice = resp.choices[0]
            raw = choice.message.content or ""
            if choice.finish_reason == "length":
                max_tokens *= 2
                continue
            try:
                return orchestrator._extract_json(raw)
            except Exception as exc:
                if attempt >= 2:
                    return None
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": (
                    f"That was not valid JSON ({exc}). Reply again with ONLY one JSON "
                    'object: {"reply": "..."} or {"tool": "...", "args": {...}}.'
                )})
        return None

    for _ in range(MAX_TOOL_ROUNDS):
        action = _next_action()
        if action is None:
            yield emit(save("assistant",
                 "I applied the actions above, but had trouble wrapping up — ask me to continue if something's missing."
                 if tools_ran else
                 "Sorry, I had trouble forming a response — please try again."))
            yield {"type": "done"}
            return

        if "reply" in action:
            yield emit(save("assistant", str(action["reply"])))
            yield {"type": "done"}
            return

        tool = action.get("tool", "")
        args = action.get("args", {}) or {}

        step_key += 1
        key = step_key
        yield {
            "type": "step", "key": key, "tool": tool, "status": "running",
            "label": TOOL_RUNNING_LABEL.get(tool, f"Running {tool}"),
        }

        try:
            result = _run_tool(db, tool, args)
        except (ValidationError, ValueError) as exc:
            result = f"error: {exc}"
        tools_ran = True

        failed = isinstance(result, str) and result.startswith("error:")
        yield {
            "type": "step", "key": key, "tool": tool,
            "status": "error" if failed else "done",
            "label": result if failed else TOOL_DONE_LABEL.get(tool, f"{tool} finished"),
            "detail": _step_detail(tool, result),
        }

        # Surface newly created tasks so the UI can render them as a live,
        # tickable checklist rather than an opaque "task added" note.
        created = _created_tasks(db, result)
        if created:
            yield {"type": "tasks", "tasks": created}

        yield emit(save("tool", json.dumps(result) if not isinstance(result, str) else result,
             tool_calls=[{"tool": tool, "args": args}]))
        messages.append({"role": "assistant", "content": json.dumps({"tool": tool, "args": args})})
        messages.append({"role": "user", "content": f"[tool result] {json.dumps(result, default=str)[:3000]}"})

    yield emit(save("assistant", "I hit my tool-call limit for this message — the actions above were applied."))
    yield {"type": "done"}


def _step_detail(tool: str, result) -> str | None:
    """One short line under a completed step — what it actually found or did."""
    if isinstance(result, str):
        return None
    if tool == "query" and isinstance(result, list):
        return f"{len(result)} result{'' if len(result) == 1 else 's'}"
    if tool == "replan" and isinstance(result, dict):
        warns = result.get("warnings") or []
        return f"{len(warns)} warning{'' if len(warns) == 1 else 's'}" if warns else None
    if tool == "add_tasks" and isinstance(result, dict):
        n = len(result.get("created") or [])
        return f"{n} task{'' if n == 1 else 's'}"
    return None


def _created_tasks(db: Session, result) -> list[dict]:
    """Full rows for any task ids a tool just created, for the result card."""
    if isinstance(result, str) or not isinstance(result, dict):
        return []
    ids = []
    if "created_task_id" in result:
        ids.append(result["created_task_id"])
    for item in result.get("created") or []:
        if isinstance(item, dict) and item.get("created_task_id"):
            ids.append(item["created_task_id"])
    if not ids:
        return []
    out = []
    for tid in ids:
        task = db.get(Task, uuid_mod.UUID(tid))
        if task:
            out.append({
                "id": str(task.id),
                "title": task.title,
                "due_date": str(task.due_date) if task.due_date else None,
                "priority": task.priority,
                "category": task.category,
                "estimated_minutes": task.estimated_minutes,
                "status": task.status,
            })
    return out


def _create_task(db: Session, a: AddTaskArgs) -> dict:
    """Create one task (shared by add_task and add_tasks)."""
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


def _run_tool(db: Session, tool: str, args: dict):
    if tool == "add_task":
        return _create_task(db, AddTaskArgs.model_validate(args))

    if tool == "add_tasks":
        a = AddTasksArgs.model_validate(args)
        return {"created": [_create_task(db, t) for t in a.tasks]}

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
