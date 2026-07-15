"""Summary + task extraction pipeline (LLM jobs 1 and 2).

Each job is independent: a summary failure doesn't block task extraction and
vice versa. Task reconciliation keeps ids stable across re-extracts and never
touches user-edited rows.
"""
import difflib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Meeting, Person, Task
from ..schemas import ExtractResult, MinutesResult, SummaryResult
from . import orchestrator, prompts

logger = logging.getLogger(__name__)

TITLE_MATCH_THRESHOLD = 0.75

# Small windows = focused attention per LLM call = fewer missed tasks; they all
# run in parallel so more windows barely cost wall time. Overlapping lines keep
# commitments spanning a window boundary visible to at least one call (the
# cross-window dedupe collapses anything extracted twice).
CHUNK_CHAR_LIMIT = 3000
CHUNK_OVERLAP_LINES = 3


def _transcript_lines(meeting: Meeting) -> list[str]:
    lines = []
    for seg in meeting.segments:
        mm, ss = divmod(int(seg.start_sec), 60)
        prefix = f"[{mm:02d}:{ss:02d}]"
        speaker = seg.speaker or seg.speaker_raw  # canonical name, else raw pyannote label
        if speaker:
            prefix += f" [{speaker}]"
        lines.append(f"{prefix} {seg.text}")
    return lines


def build_transcript(meeting: Meeting) -> str:
    return "\n".join(_transcript_lines(meeting))


def _chunk_lines(
    lines: list[str], limit: int = CHUNK_CHAR_LIMIT, overlap: int = CHUNK_OVERLAP_LINES
) -> list[str]:
    """Group transcript lines into windows of at most `limit` characters.

    Each window starts with the last `overlap` lines of the previous one so a
    commitment split across the boundary is fully visible to at least one call.
    """
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        if current and size + len(line) + 1 > limit:
            chunks.append("\n".join(current))
            current = current[-overlap:] if overlap else []
            size = sum(len(l) + 1 for l in current)
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _set_progress(db: Session, meeting: Meeting, stage: str, done: int, total: int) -> None:
    meeting.extract_progress = {"stage": stage, "done": done, "total": total}
    db.commit()


# Batches fan out concurrently — the OpenAI client is thread-safe. Kept modest
# so a slow gateway isn't hammered into more timeouts.
MAX_PARALLEL_BATCHES = 4


def _run_batches(chunks: list[str], run_one, on_batch_done) -> list:
    """Run run_one(i, chunk) for every chunk in parallel, preserving order.

    on_batch_done() fires on the caller thread as each batch finishes (the DB
    session is not thread-safe, so progress commits must happen here). If any
    batch fails after the orchestrator's retries, the first failure is raised
    once all batches have settled.
    """
    results: list = [None] * len(chunks)
    failures: list[tuple[int, Exception]] = []
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_BATCHES, len(chunks))) as pool:
        futures = {pool.submit(run_one, i, chunk): i for i, chunk in enumerate(chunks)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as exc:
                failures.append((i, exc))
            else:
                on_batch_done()
    if failures:
        i, exc = min(failures)
        raise RuntimeError(f"batch {i + 1} of {len(chunks)} failed: {exc}") from exc
    return results


def run_extraction(db: Session, meeting: Meeting) -> None:
    """Run both jobs in transcript batches, collect errors, commit results +
    status atomically per stage. Progress is committed after every LLM call so
    the UI can poll it."""
    meeting.extract_status = "running"
    meeting.extract_error = None
    meeting.extract_progress = None
    db.commit()

    lines = _transcript_lines(meeting)
    if not "".join(lines).strip():
        meeting.extract_status = "failed"
        meeting.extract_error = "Transcript is empty"
        db.commit()
        return

    chunks = _chunk_lines(lines)
    n = len(chunks)
    # one summary call per chunk (+1 merge when batched) + two extract calls per
    # chunk (extract + missed-task sweep) + one minutes call (skill.md)
    total_steps = n + (1 if n > 1 else 0) + 2 * n + 1
    done = 0
    _set_progress(db, meeting, "summary", done, total_steps)

    errors: list[str] = []
    partials: list[SummaryResult] = []

    try:
        def _summary_batch(i: int, chunk: str) -> SummaryResult:
            return orchestrator.run_json_job(
                "summary",
                prompts.SUMMARY_SYSTEM,
                prompts.summary_user(chunk, part=i + 1, parts=n),
                SummaryResult,
            )

        def _tick_summary() -> None:
            nonlocal done
            done += 1
            _set_progress(db, meeting, "summary", done, total_steps)

        partials = _run_batches(chunks, _summary_batch, _tick_summary)
        if n > 1:
            final = orchestrator.run_json_job(
                "summary", prompts.SUMMARY_SYSTEM, prompts.summary_combine_user(partials), SummaryResult
            )
            done += 1
            _set_progress(db, meeting, "summary", done, total_steps)
        else:
            final = partials[0]
        meeting.summary = final.summary
        meeting.decisions = final.decisions
    except Exception as exc:
        logger.exception("Summary job failed for meeting %s", meeting.id)
        errors.append(f"summary: {exc}")
        done = n + (1 if n > 1 else 0)  # skip remaining summary steps in the bar

    extracted = []
    try:
        meeting_day = meeting.created_at.date()
        roster = _roster_block(db)

        def _extract_batch(i: int, chunk: str) -> ExtractResult:
            return orchestrator.run_json_job(
                "extract",
                prompts.EXTRACT_SYSTEM,
                prompts.extract_user(
                    chunk,
                    meeting_day.isoformat(),
                    meeting_day.strftime("%A"),
                    part=i + 1,
                    parts=n,
                    roster=roster,
                ),
                ExtractResult,
            )

        def _tick_extract() -> None:
            nonlocal done
            done += 1
            _set_progress(db, meeting, "extract", done, total_steps)

        # Wave 1: extract every window in parallel.
        wave1 = _run_batches(chunks, _extract_batch, _tick_extract)

        # Wave 2 (also parallel): per window, re-read and hunt ONLY for tasks
        # wave 1 missed. Best-effort — a sweep failure never fails extraction,
        # it just means no extra recall for that window.
        def _sweep_batch(i: int, chunk: str) -> ExtractResult:
            found_block = "\n".join(
                f"- {t.title} (owner: {t.owner or 'null'})" for t in wave1[i].tasks
            )
            return orchestrator.run_json_job(
                "extract",
                prompts.EXTRACT_SYSTEM,
                prompts.extract_sweep_user(
                    chunk,
                    meeting_day.isoformat(),
                    meeting_day.strftime("%A"),
                    found_block,
                    part=i + 1,
                    parts=n,
                    roster=roster,
                ),
                ExtractResult,
            )

        for result in wave1:
            extracted.extend(result.tasks)
        try:
            for result in _run_batches(chunks, _sweep_batch, _tick_extract):
                extracted.extend(result.tasks)
        except Exception:
            logger.exception("Missed-task sweep failed for meeting %s; keeping wave-1 tasks", meeting.id)
            done = n + (1 if n > 1 else 0) + 2 * n  # skip remaining sweep steps in the bar

        extracted = _dedupe_tasks(extracted)
        _reconcile_tasks(db, meeting, ExtractResult(tasks=extracted))
    except Exception as exc:
        logger.exception("Extraction job failed for meeting %s", meeting.id)
        errors.append(f"extract: {exc}")

    # Smart meeting notes (skill.md): synthesized from the already-computed
    # summaries + tasks, so it's one small call regardless of transcript length.
    # A failure here degrades gracefully — summary/tasks are already saved.
    try:
        _set_progress(db, meeting, "notes", done, total_steps)
        # Give the minutes job the raw transcript when it fits in one call;
        # very long meetings fall back to the per-part summaries alone.
        full_transcript = "\n".join(lines)
        result = orchestrator.run_json_job(
            "minutes",
            prompts.minutes_system(),
            prompts.minutes_user(
                _minutes_metadata(meeting),
                meeting.summary or "",
                meeting.decisions or [],
                _minutes_tasks_block(extracted),
                [p.summary for p in partials],
                transcript=full_transcript if len(full_transcript) <= 16000 else "",
            ),
            MinutesResult,
        )
        meeting.notes = result.notes
        done += 1
        _set_progress(db, meeting, "notes", done, total_steps)
    except Exception as exc:
        logger.exception("Minutes job failed for meeting %s", meeting.id)
        errors.append(f"notes: {exc}")

    meeting.extract_status = "failed" if errors else "done"
    meeting.extract_error = "; ".join(str(e)[:500] for e in errors) if errors else None
    meeting.extract_progress = None
    db.commit()


def _roster_block(db: Session) -> str:
    people = db.scalars(select(Person)).all()
    return "\n".join(
        f"- {p.name}" + (f" (aliases: {', '.join(p.aliases)})" if p.aliases else "")
        for p in people
    )


def _minutes_metadata(meeting: Meeting) -> str:
    attendees = sorted({s.speaker for s in meeting.segments if s.speaker})
    duration = f"{round((meeting.duration_sec or 0) / 60)} min" if meeting.duration_sec else "unknown"
    attendee_line = (
        ", ".join(attendees) if attendees else "(no speaker labels — infer from the transcript)"
    )
    return (
        f"- Title: {meeting.title}\n"
        f"- Date: {meeting.created_at.date().isoformat()}\n"
        f"- Duration: {duration}\n"
        f"- Attendees identified from speaker labels: {attendee_line}"
    )


def _minutes_tasks_block(tasks: list) -> str:
    if not tasks:
        return "(no action items extracted)"
    lines = []
    for i, t in enumerate(tasks, 1):
        lines.append(
            f"- [A{i}] {t.title} — Owner: {t.owner or 'TBD'} — Due: {t.due_date.isoformat() if t.due_date else 'TBD'}"
            + (f" — Priority: {t.priority}" if t.priority else "")
        )
    return "\n".join(lines)


def _dedupe_tasks(tasks: list) -> list:
    """Drop near-identical extracted tasks (same action mentioned twice)."""
    kept = []
    for t in tasks:
        duplicate = any(
            difflib.SequenceMatcher(None, k.title.lower(), t.title.lower()).ratio() >= 0.85
            and (k.owner or "").lower() == (t.owner or "").lower()
            for k in kept
        )
        if not duplicate:
            kept.append(t)
    return kept


def _reconcile_tasks(db: Session, meeting: Meeting, result: ExtractResult) -> None:
    """Match new extraction against existing tasks by fuzzy title.

    Matched tasks are updated in place (id preserved); edited tasks are never
    modified. Stale unmatched tasks are deleted only if unedited. New tasks
    are inserted. All within the caller's transaction.
    """
    existing = list(meeting.tasks)
    unmatched = set(id(t) for t in existing)

    for new in result.tasks:
        best, best_score = None, 0.0
        for task in existing:
            if id(task) not in unmatched:
                continue
            score = difflib.SequenceMatcher(
                None, task.title.lower().strip(), new.title.lower().strip()
            ).ratio()
            if score > best_score:
                best, best_score = task, score

        if best is not None and best_score >= TITLE_MATCH_THRESHOLD:
            unmatched.discard(id(best))
            if not best.edited:
                best.title = new.title
                best.owner = new.owner
                best.due_date = new.due_date
                best.priority = new.priority
                best.dependencies = new.dependencies
                best.source_quote = new.source_quote
        else:
            db.add(
                Task(
                    meeting_id=meeting.id,
                    title=new.title,
                    owner=new.owner,
                    due_date=new.due_date,
                    priority=new.priority,
                    dependencies=new.dependencies,
                    source_quote=new.source_quote,
                )
            )

    for task in existing:
        if id(task) in unmatched and not task.edited:
            db.delete(task)
