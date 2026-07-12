import datetime as dt
import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Text, Time, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    audio_key: Mapped[str] = mapped_column(Text, nullable=False)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="uploaded")
    error: Mapped[str | None] = mapped_column(Text)
    diarize_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    speaker_map: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    summary: Mapped[str | None] = mapped_column(Text)
    decisions: Mapped[list | None] = mapped_column(JSONB)
    extract_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    extract_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    segments: Mapped[list["Segment"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="Segment.idx"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="Task.created_at"
    )


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str | None] = mapped_column(Text)  # canonical person name after mapping
    speaker_raw: Mapped[str | None] = mapped_column(Text)  # pyannote label ("SPEAKER_00"), kept for re-mapping

    meeting: Mapped[Meeting] = relationship(back_populates="segments")

    __table_args__ = (Index("idx_segments_meeting", "meeting_id", "idx"),)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str | None] = mapped_column(Text)  # high | medium | low | NULL
    dependencies: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    source_quote: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open", server_default="open")
    edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    assignment: Mapped[str] = mapped_column(Text, nullable=False, default="others", server_default="others")
    assignment_reason: Mapped[str | None] = mapped_column(Text)
    assignment_source: Mapped[str] = mapped_column(Text, nullable=False, default="llm", server_default="llm")
    segment_idx: Mapped[int | None] = mapped_column(Integer)  # best-match segment for highlighting
    category: Mapped[str] = mapped_column(Text, nullable=False, default="work", server_default="work")
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)
    estimate_source: Mapped[str] = mapped_column(Text, nullable=False, default="llm", server_default="llm")
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    start_date: Mapped[date | None] = mapped_column(Date)
    at_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped[Meeting] = relationship(back_populates="tasks")
    blocks: Mapped[list["ScheduleBlock"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="ScheduleBlock.start_at"
    )

    __table_args__ = (
        Index("idx_tasks_meeting", "meeting_id"),
        Index("idx_tasks_owner", "owner"),
        Index("idx_tasks_assignment", "assignment"),
    )


class AvailabilityRule(Base):
    __tablename__ = "availability_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(Text, nullable=False)  # work | personal
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon … 6=Sun
    start_t: Mapped[time] = mapped_column(Time, nullable=False)
    end_t: Mapped[time] = mapped_column(Time, nullable=False)


class BusyBlock(Base):
    __tablename__ = "busy_blocks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    weekday: Mapped[int | None] = mapped_column(Integer)  # recurring weekly if set
    # NB: annotation must not shadow the attribute name, or nullability breaks
    date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # one-off if set
    start_t: Mapped[time] = mapped_column(Time, nullable=False)
    end_t: Mapped[time] = mapped_column(Time, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual", server_default="manual")


class ScheduleBlock(Base):
    __tablename__ = "schedule_blocks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="planned", server_default="planned")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    gcal_event_id: Mapped[str | None] = mapped_column(Text)

    task: Mapped["Task"] = relationship(back_populates="blocks")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # user | assistant | tool
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict | list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Person(Base):
    __tablename__ = "people"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    is_me: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
