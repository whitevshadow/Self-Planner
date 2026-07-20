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
from ..schemas import ExtractResult, MinutesResult, SummaryResult, TaskMatchResult
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
    """Drop near-identical extracted tasks (same action mentioned twice).

    The two extraction waves often surface the same commitment with a different
    owner guess (e.g. "Anish" vs null). Treat those as one task — matching titles
    with a compatible owner (equal, or either side unknown) collapse, and the
    surviving row keeps whichever owner is actually named.
    """
    kept = []
    for t in tasks:
        merged = False
        for k in kept:
            if difflib.SequenceMatcher(None, k.title.lower(), t.title.lower()).ratio() < 0.85:
                continue
            ko, to = (k.owner or "").lower(), (t.owner or "").lower()
            if ko == to or not ko or not to:
                if not k.owner and t.owner:  # keep the named owner over a blank one
                    k.owner = t.owner
                merged = True
                break
        if not merged:
            kept.append(t)
    return kept


def _title_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _update_from(task: Task, new) -> None:
    """Copy re-extracted fields onto an existing task, preserving its id."""
    task.title = new.title
    task.owner = new.owner
    task.due_date = new.due_date
    task.priority = new.priority
    task.dependencies = new.dependencies
    task.source_quote = new.source_quote


def _new_task(meeting_id, new) -> Task:
    return Task(
        meeting_id=meeting_id,
        title=new.title,
        owner=new.owner,
        due_date=new.due_date,
        priority=new.priority,
        dependencies=new.dependencies,
        source_quote=new.source_quote,
    )


def _reconcile_tasks(db: Session, meeting: Meeting, result: ExtractResult) -> None:
    """Reconcile re-extracted tasks against existing ones, preserving task ids.

    On a re-extraction (existing tasks present) an LLM maps each candidate to an
    existing task id — so a task keeps its identity even if its wording changed a
    lot between runs, which plain title matching would miss and duplicate. The
    deterministic title match is the fallback when there is nothing to match
    against yet, or if the LLM call fails. Edited tasks are never modified;
    unmatched unedited tasks are deleted. All within the caller's transaction.
    """
    existing = list(meeting.tasks)
    new_tasks = result.tasks

    if existing and new_tasks:
        try:
            matches = _match_via_llm(new_tasks, existing)  # LLM call first — no mutation yet
        except Exception:
            logger.exception("LLM reconcile failed for meeting %s; using title match", meeting.id)
        else:
            _apply_matches(db, meeting, new_tasks, existing, matches)
            return

    _reconcile_by_title(db, meeting, new_tasks, existing)


def _match_via_llm(new_tasks, existing) -> dict[int, Task | None]:
    """Ask the LLM to map candidate index → existing task (or None = new)."""
    existing_block = "\n".join(
        f"- id: {t.id}\n  title: {t.title}\n  owner: {t.owner or 'null'}" for t in existing
    )
    candidates_block = "\n".join(
        f"- candidate_index: {i}\n  title: {t.title}\n  owner: {t.owner or 'null'}"
        for i, t in enumerate(new_tasks)
    )
    result = orchestrator.run_json_job(
        "extract",
        prompts.RECONCILE_SYSTEM,
        prompts.reconcile_user(existing_block, candidates_block),
        TaskMatchResult,
    )
    by_id = {str(t.id): t for t in existing}
    mapping: dict[int, Task | None] = {}
    for m in result.matches:
        if 0 <= m.candidate_index < len(new_tasks):
            mapping[m.candidate_index] = by_id.get(m.existing_id) if m.existing_id else None
    return mapping


def _apply_matches(db, meeting, new_tasks, existing, mapping: dict[int, Task | None]) -> None:
    matched: set[int] = set()
    known_titles = [t.title for t in existing]
    for i, new in enumerate(new_tasks):
        target = mapping.get(i)
        if target is not None and id(target) not in matched:
            matched.add(id(target))
            if not target.edited:
                _update_from(target, new)
            known_titles.append(new.title)
        elif any(_title_ratio(t, new.title) >= TITLE_MATCH_THRESHOLD for t in known_titles):
            continue  # new/redundant but duplicates something we already have — skip
        else:
            db.add(_new_task(meeting.id, new))
            known_titles.append(new.title)

    for task in existing:
        if id(task) not in matched and not task.edited:
            db.delete(task)


def _reconcile_by_title(db, meeting, new_tasks, existing) -> None:
    """Deterministic fallback: fuzzy title match, preserving ids and edited rows."""
    unmatched = set(id(t) for t in existing)
    known_titles = [t.title for t in existing]

    for new in new_tasks:
        best, best_score = None, 0.0
        for task in existing:
            if id(task) not in unmatched:
                continue
            score = _title_ratio(task.title, new.title)
            if score > best_score:
                best, best_score = task, score

        if best is not None and best_score >= TITLE_MATCH_THRESHOLD:
            unmatched.discard(id(best))
            if not best.edited:
                _update_from(best, new)
        elif any(_title_ratio(t, new.title) >= TITLE_MATCH_THRESHOLD for t in known_titles):
            continue  # matches a task already claimed (e.g. an edited one) — skip
        else:
            db.add(_new_task(meeting.id, new))
            known_titles.append(new.title)

    for task in existing:
        if id(task) in unmatched and not task.edited:
            db.delete(task)
