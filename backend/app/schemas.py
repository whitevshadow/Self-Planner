import uuid
from datetime import date, datetime
from datetime import date as dt_date
from datetime import time as dt_time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    idx: int
    start_sec: float
    end_sec: float
    text: str
    speaker: str | None = None
    speaker_raw: str | None = None


class MeetingListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    filename: str
    status: str
    duration_sec: float | None = None
    error: str | None = None
    has_audio: bool = True
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    meeting_id: uuid.UUID
    title: str
    owner: str | None = None
    due_date: date | None = None
    priority: str | None = None
    dependencies: list[str] = []
    source_quote: str | None = None
    status: str
    edited: bool
    assignment: str = "others"
    assignment_reason: str | None = None
    assignment_source: str = "llm"
    segment_idx: int | None = None
    category: str = "work"
    estimated_minutes: int | None = None
    estimate_source: str = "llm"
    intensity: Literal["heavy", "light"] | None = None
    steps: list[str] = []
    progress: int = 0
    start_date: date | None = None
    at_risk: bool = False
    created_at: datetime


class TaskUpdate(BaseModel):
    title: str | None = None
    owner: str | None = None
    due_date: date | None = None
    start_date: date | None = None
    priority: Literal["high", "medium", "low"] | None = None
    status: Literal["open", "done", "dropped"] | None = None
    category: Literal["work", "personal"] | None = None
    estimated_minutes: int | None = Field(default=None, ge=5, le=960)
    progress: int | None = Field(default=None, ge=0, le=100)
    intensity: Literal["heavy", "light"] | None = None  # null = auto
    # Distinguish "field omitted" from "field set to null" via model_fields_set.


class MeetingTextIn(BaseModel):
    """Create a meeting from a pasted transcript / notes instead of audio."""

    title: str | None = None
    text: str = Field(min_length=1)


class MeetingDetail(MeetingListItem):
    summary: str | None = None
    decisions: list[str] | None = None
    notes: str | None = None
    extract_status: str = "pending"
    extract_error: str | None = None
    extract_progress: dict | None = None
    diarize_status: str = "pending"
    speaker_map: dict[str, str] = {}
    segments: list[SegmentOut] = []
    tasks: list[TaskOut] = []


# --- LLM job output schemas (validation gate before any DB write) ---

class SummaryResult(BaseModel):
    summary: str = Field(min_length=1)
    decisions: list[str] = []


class MinutesResult(BaseModel):
    notes: str = Field(min_length=1)  # full minutes as Markdown


_NULLISH_OWNERS = {"", "null", "none", "unknown", "unclear", "unassigned", "tbd", "someone", "team", "we", "everyone", "anyone"}


class ExtractedTask(BaseModel):
    title: str = Field(min_length=1)
    owner: str | None = None
    due_date: date | None = None
    priority: Literal["high", "medium", "low"] | None = None
    dependencies: list[str] = []
    source_quote: str | None = None

    @field_validator("title", mode="after")
    @classmethod
    def _clean_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be blank")
        return v[0].upper() + v[1:]

    @field_validator("owner", mode="before")
    @classmethod
    def _normalize_owner(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return None if v.lower() in _NULLISH_OWNERS else v

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        if v is None:
            return None
        v = str(v).strip().lower()
        return v if v in ("high", "medium", "low") else None

    @field_validator("dependencies", mode="before")
    @classmethod
    def _clean_dependencies(cls, v):
        if not v:
            return []
        return [str(d).strip() for d in v if str(d).strip()]


class ExtractResult(BaseModel):
    tasks: list[ExtractedTask] = []


class TaskMatch(BaseModel):
    """Maps one re-extracted candidate to an existing task id (or null = new)."""
    candidate_index: int
    existing_id: str | None = None


class TaskMatchResult(BaseModel):
    matches: list[TaskMatch] = []


class TaskClassification(BaseModel):
    task_id: str
    assignment: Literal["mine", "maybe", "others"]
    reason: str = ""
    owner_normalized: str | None = None


class ClassifyResult(BaseModel):
    classifications: list[TaskClassification] = []


class PersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    aliases: list[str] = []
    is_me: bool


class PersonIn(BaseModel):
    name: str = Field(min_length=1)
    aliases: list[str] = []
    is_me: bool = False


# --- Phase 4: planning ---

class TaskTriage(BaseModel):
    """Triage job output: what a task is worth, how long it takes, and when it runs."""

    task_id: str
    priority: Literal["high", "medium", "low"]
    estimated_minutes: int = Field(ge=5, le=960)
    steps: list[str] = []
    start_date: date | None = None
    due_date: date | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def _normalize_priority(cls, v):
        v = str(v or "").strip().lower()
        return v if v in ("high", "medium", "low") else "medium"


class TriageResult(BaseModel):
    triages: list[TaskTriage] = []


class AssignMineIn(BaseModel):
    task_ids: list[uuid.UUID] = Field(min_length=1)


class AvailabilityRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: Literal["work", "personal"]
    weekday: int = Field(ge=0, le=6)
    start_t: dt_time
    end_t: dt_time
    energy: Literal["deep", "shallow"] = "deep"


class AvailabilityRuleIn(BaseModel):
    category: Literal["work", "personal"]
    weekday: int = Field(ge=0, le=6)
    start_t: dt_time
    end_t: dt_time
    energy: Literal["deep", "shallow"] = "deep"


class BusyBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    weekday: int | None = None
    date: dt_date | None = None
    start_t: dt_time
    end_t: dt_time
    source: str


class BusyBlockIn(BaseModel):
    label: str = Field(min_length=1)
    weekday: int | None = Field(default=None, ge=0, le=6)
    date: dt_date | None = None
    start_t: dt_time
    end_t: dt_time


class ScheduleBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    status: str
    pinned: bool
    gcal_event_id: str | None = None


class ScheduleBlockPatch(BaseModel):
    status: Literal["planned", "in_progress", "done", "skipped"] | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


class PlanWarningOut(BaseModel):
    task_id: str
    title: str
    kind: str
    detail: str


class DayBlock(BaseModel):
    """Schedule block joined with its task for the day-plan view."""
    id: uuid.UUID
    task_id: uuid.UUID
    task_title: str
    category: str
    priority: str | None = None
    start_at: datetime
    end_at: datetime
    status: str
    pinned: bool
    at_risk: bool


class PlanResponse(BaseModel):
    warnings: list[PlanWarningOut] = []
    today: list[DayBlock] = []


class NowBlock(BaseModel):
    """A single schedule block for the live 'now' view."""
    id: uuid.UUID
    task_id: uuid.UUID
    task_title: str
    category: str
    priority: str | None = None
    start_at: datetime
    end_at: datetime
    status: str


class NowView(BaseModel):
    """Deterministic 'what am I doing right now' snapshot — no LLM."""
    now: datetime
    current: NowBlock | None = None  # block spanning the current moment
    next: NowBlock | None = None  # next block starting after now (may be a later day)
    free_minutes: int | None = None  # minutes until `next` starts, when nothing is current


class BlockExtendIn(BaseModel):
    minutes: int = Field(default=15, ge=5, le=120)


class TimetableEntry(BaseModel):
    day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    start: str = Field(pattern=r"^\d{1,2}:\d{2}$")
    end: str = Field(pattern=r"^\d{1,2}:\d{2}$")
    label: str = Field(min_length=1)


class TimetableParseResult(BaseModel):
    entries: list[TimetableEntry] = []


class ChatIn(BaseModel):
    message: str = Field(min_length=1)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    tool_calls: list | dict | None = None
    created_at: datetime
