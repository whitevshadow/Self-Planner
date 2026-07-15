"""Idempotent schema upgrades for existing dev databases.

`Base.metadata.create_all` only creates missing tables — these ALTERs bring
tables created in earlier phases up to the current model.
"""
from sqlalchemy import text

from .db import engine

STATEMENTS = [
    # Phase 2
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS summary TEXT",
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS decisions JSONB",
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS extract_status TEXT NOT NULL DEFAULT 'pending'",
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS extract_error TEXT",
    # Phase 3
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS diarize_status TEXT NOT NULL DEFAULT 'pending'",
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS speaker_map JSONB NOT NULL DEFAULT '{}'",
    "ALTER TABLE segments ADD COLUMN IF NOT EXISTS speaker_raw TEXT",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignment TEXT NOT NULL DEFAULT 'others'",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignment_reason TEXT",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignment_source TEXT NOT NULL DEFAULT 'llm'",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS segment_idx INT",
    "CREATE INDEX IF NOT EXISTS idx_tasks_assignment ON tasks (assignment)",
    # Phase 4
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'work'",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS estimated_minutes INT",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS estimate_source TEXT NOT NULL DEFAULT 'llm'",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS steps JSONB NOT NULL DEFAULT '[]'",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS progress INT NOT NULL DEFAULT 0",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_date DATE",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS at_risk BOOLEAN NOT NULL DEFAULT false",
    # busy_blocks.date was created NOT NULL by an annotation-shadowing bug
    "ALTER TABLE busy_blocks ALTER COLUMN date DROP NOT NULL",
    # Batched extraction progress ({"stage", "done", "total"})
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS extract_progress JSONB",
    # Smart meeting notes (Markdown minutes generated per services/skill.md)
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS notes TEXT",
]


def run_migrations() -> None:
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
