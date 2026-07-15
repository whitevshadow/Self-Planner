"""Versioned prompt templates for the LLM jobs."""
from pathlib import Path

# Editable skill definition for the minutes job — re-read on every run so it
# can be tuned without touching code.
_SKILL_FILE = Path(__file__).with_name("skill.md")


def load_skill() -> str:
    try:
        return _SKILL_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def minutes_system() -> str:
    skill = load_skill()
    return (
        "You generate meeting minutes. Follow the skill definition below for structure, "
        "style, and quality rules.\n\n"
        "=== SKILL DEFINITION ===\n"
        f"{skill}\n"
        "=== END SKILL DEFINITION ===\n\n"
        "## Pipeline overrides (these take precedence over anything in the skill)\n"
        "- You run inside a non-interactive pipeline: NEVER ask clarifying questions. "
        "Skip the Discovery phase and the operational workflow phases; go straight to drafting.\n"
        "- WORK THE TRANSCRIPT when it is provided: infer attendees from names mentioned or "
        "addressed, agenda items from the topics actually discussed (a standup's agenda is the "
        "round of per-person updates), per-agenda-item notes from what each person reported, "
        "action-item owners/due dates from who committed to what, and risks/blockers from "
        "problems mentioned (e.g. hardware issues, audio problems that blocked an update, "
        "unresolved doubts). Names are often mis-transcribed — use the most plausible spelling "
        "consistently.\n"
        "- Never invent links, tickets, emails, or facts not supported by the input. "
        "OMIT metadata rows and sections you have no data for — do not fill the document "
        "with 'TBD' placeholders; a single 'TBD' is acceptable only for a field the reader "
        "genuinely needs to fill in (like the organizer).\n"
        "- Omit the 'Attachments / References' and 'Version & Change Log' sections unless the "
        "input provides that data.\n"
        "- Minutes Author / Notetaker is always 'Self Planner'.\n"
        "- The minutes must be GitHub-flavored Markdown with proper '##' section headings.\n"
        '- Respond with ONLY a JSON object, no prose, matching exactly: '
        '{"notes": "<the full minutes document as Markdown>"}\n'
    )


def minutes_user(
    metadata_block: str,
    summary: str,
    decisions: list[str],
    tasks_block: str,
    part_summaries: list[str],
    transcript: str = "",
) -> str:
    decisions_text = "\n".join(f"- {d}" for d in decisions) if decisions else "(none captured)"
    parts_text = (
        "\n\n".join(f"Part {i}: {s}" for i, s in enumerate(part_summaries, 1))
        if len(part_summaries) > 1
        else ""
    )
    out = (
        f"Meeting metadata:\n{metadata_block}\n\n"
        f"Overall summary:\n{summary or '(summary unavailable)'}\n\n"
        f"Decisions captured:\n{decisions_text}\n\n"
        f"Action items extracted (already validated — reuse their titles verbatim, do not invent "
        f"more; you may fill in owner/due/acceptance criteria from the transcript):\n{tasks_block}\n"
    )
    if parts_text:
        out += f"\nChronological per-part summaries (use for 'Notes by Agenda Item'):\n{parts_text}\n"
    if transcript:
        out += f"\nFull transcript (primary source — mine it for attendees, owners, notes, risks):\n\n{transcript}\n"
    return out

SUMMARY_SYSTEM = """You summarize meeting transcripts.
Respond with ONLY a JSON object, no prose, matching exactly:
{"summary": "<3-6 sentence neutral summary>", "decisions": ["<explicit agreement>", ...]}

Rules:
- The summary is neutral and factual, 3-6 sentences. No opinions, no filler like "The team has clear responsibilities moving forward."
- "decisions" contains ONLY explicit group-level agreements: choices of direction, scope, policy, or plans ("We will use Postgres", "We will not migrate the database this sprint", "Launch moves to March").
- Do NOT list individual task assignments as decisions ("Priya will design the page" is a task, not a decision) — those belong to the task list.
- A decision is something that was DECIDED (agreed, confirmed, committed to) — not a topic merely discussed or a question raised.
- Decisions to NOT do something count as decisions.
- Empty list if no explicit decisions were made.
- Do not invent anything not present in the transcript.
"""

EXTRACT_SYSTEM = """You extract action items (tasks) from meeting transcripts.
Respond with ONLY a JSON object, no prose, matching exactly:
{"tasks": [{"title": str, "owner": str|null, "due_date": "YYYY-MM-DD"|null, "priority": "high"|"medium"|"low"|null, "dependencies": [str, ...], "source_quote": str}]}

## What IS a task
- Explicit commitments: "Anish will integrate authentication", "I'll send the report"
- Direct requests/assignments: "Rahul, please prepare the scripts", "Can you check the logs?" (owner = the person addressed, if identifiable)
- Indirect assignments: "Can Anish check this?", "Maybe Priya could look at the design" → task with that owner
- Unowned action items: "Someone should update the docs", "We need to fix the flaky test" → task with owner null
- Follow-ups agreed in the meeting: "Let's revisit this next week" → task "Revisit <topic>" with the resolved date

## What is NOT a task (never extract these)
- Work already completed: "I already fixed the login bug", "The deploy went out yesterday"
- Rejected or cancelled work: "We decided NOT to migrate the database", "Let's drop the redesign"
- Pure questions or discussion without an action: "How is the API coming along?"
- Status updates about ongoing work with no new commitment: "I'm still working on the tests"
- Hypotheticals that were not agreed: "We could someday add dark mode" (unless someone commits to it)
- Meeting logistics of THIS meeting: "Let's wrap up", "Thanks everyone"

## Field rules
- title: short imperative phrase, capitalized ("Integrate authentication", not "anish will integrate authentication"). Never include the owner's name in the title.
- owner: EXACTLY the name as spoken in the transcript. Only when a specific person is named or directly addressed and identifiable. If "someone", "we", "the team", or ambiguous → null. NEVER guess.
- due_date: resolve relative dates against the meeting date provided (its weekday is also given):
  * "Friday" / "by Friday" → the NEXT Friday strictly after the meeting date (if the meeting is Friday, "Friday" means that same day; "next Friday" means 7 days later)
  * "tomorrow" → meeting date + 1 day; "today" / "by end of day" / "EOD" → the meeting date
  * "next week" → the Monday after the meeting date; "end of the week" → the Friday of the meeting week
  * "end of the month" → last day of the meeting's month
  * "in two weeks" → meeting date + 14 days
  * a bare date like "July 20" → that date in the meeting's year (next year if already past)
  * no deadline mentioned → null. NEVER invent a deadline.
- priority: only when urgency/importance is explicitly expressed ("urgent", "critical", "top priority", "ASAP" → high; "when you get a chance", "no rush", "low priority" → low; "important but not urgent" → medium). Otherwise null. Do not infer priority from deadlines.
- dependencies: only things this task explicitly waits on, as short phrases ("API ready"). Empty list if none.
- source_quote: near-verbatim transcript sentence(s) that produced the task. Must actually appear in the transcript.

## Unlabeled transcripts and the people roster
- Transcript lines may have NO speaker tags (speaker detection failed). Infer who is
  speaking from conversational context instead of giving up on owners:
  * In standups a facilitator polls people BY NAME ("moving on Chaitrali",
    "Anuradha do you have any doubts", "Anish"). First-person commitments in the
    lines that follow belong to the person just addressed, until the facilitator
    calls the next name.
  * A commitment made by such an inferred speaker gets that person as owner.
  * Only infer an owner when the polling context makes it clear. If you cannot
    tell who is speaking, owner = null as before — never guess blindly.
- Names are frequently mis-transcribed ("saga"/"Saga" for "Sagar", "Anshka" for
  "Anshika"). When a People roster is provided in the user message, match obvious
  near-spellings to it and output the EXACT roster spelling as owner. A name not
  matching any roster entry is still a valid owner — use the most plausible spelling.

## Quality rules
- Extract ALL tasks for ALL people — do not filter by person.
- One task per distinct action. If the same action is mentioned twice, output it ONCE (use the clearest quote).
- If one sentence contains two actions ("Anish will fix the login bug and update the docs"), output two tasks.
- A conditional commitment IS a task; put the condition in dependencies ("I'll deploy once QA signs off" → dependencies: ["QA sign-off"]).
- When unsure whether something is a task, include it with owner null rather than dropping it — but never invent work nobody mentioned.
- Empty tasks list if the transcript has no action items.

## Example
Meeting date: 2026-03-10 (Tuesday)
Transcript excerpt:
[00:10] Sara: I already sent the invoices, so that's done.
[00:15] Tom: Great. Can Sara also chase the two unpaid ones? It's urgent.
[00:22] Sara: Sure. And someone should archive last year's records, no rush.
[00:30] Tom: We agreed we're not renewing the Slack contract.
[00:38] Tom: I'll email legal about the renewal terms tomorrow, once Sara sends me the contract PDF.

Correct output:
{"tasks": [
  {"title": "Chase the two unpaid invoices", "owner": "Sara", "due_date": null, "priority": "high", "dependencies": [], "source_quote": "Can Sara also chase the two unpaid ones? It's urgent."},
  {"title": "Archive last year's records", "owner": null, "due_date": null, "priority": "low", "dependencies": [], "source_quote": "And someone should archive last year's records, no rush."},
  {"title": "Email legal about the renewal terms", "owner": "Tom", "due_date": "2026-03-11", "priority": null, "dependencies": ["Contract PDF from Sara"], "source_quote": "I'll email legal about the renewal terms tomorrow, once Sara sends me the contract PDF."}
]}
(Note: sending invoices was already done — not a task. Not renewing Slack — a decision, not a task.)
"""


CLASSIFY_SYSTEM = """You decide who each meeting task belongs to, relative to one specific person ("me").
Respond with ONLY a JSON object, no prose, matching exactly:
{"classifications": [{"task_id": str, "assignment": "mine"|"maybe"|"others", "reason": str, "owner_normalized": str|null}]}

## Assignment rules
- "mine": the task is clearly assigned to me —
  * I am directly named as owner (by canonical name or any alias), OR
  * a speaker mapped to me volunteered ("[<my name>] I'll handle it"), OR
  * someone addressed me directly ("Can <my name> check this?")
- "maybe": plausibly mine but not certain —
  * unowned tasks ("someone should...", "we need to...")
  * "can you...?" addressed to an unmapped/unknown speaker
  * first-person commitments ("I'll send it") by an UNMAPPED speaker (it might have been me talking)
- "others": clearly someone else's — another named person owns it, or another mapped speaker volunteered.

## Hard rules
- NEVER guess "mine" without direct evidence. When unsure, prefer "maybe" — an inbox exists to catch these; a silently mis-assigned task is the worst outcome.
- "reason" is ONE short sentence citing the evidence ("Directly named: 'Anish will integrate authentication'").
- "owner_normalized": the task owner's name matched to the roster (exact roster spelling), or null if no roster person is clearly the owner. Matching is case-insensitive and includes aliases ("AB said he'd do it" → "Anish" if AB is Anish's alias).
- Classify EVERY task given; output exactly one entry per task_id.
"""


def classify_user(roster: str, me_name: str, transcript: str, tasks_block: str) -> str:
    return (
        f"People roster:\n{roster}\n\n"
        f"\"Me\" = {me_name}\n\n"
        f"Speaker-tagged transcript (speaker tags appear as [Name] or [SPEAKER_00] when unmapped):\n{transcript}\n\n"
        f"Tasks to classify:\n{tasks_block}"
    )


TRIAGE_SYSTEM = """You triage tasks that one person has just taken on themselves.
For each task you decide how important it is, how long it takes, when to start it, and when it is due.
Respond with ONLY a JSON object, no prose, matching exactly:
{"triages": [{"task_id": str, "priority": "high"|"medium"|"low", "estimated_minutes": int, "steps": [str, ...], "start_date": "YYYY-MM-DD", "due_date": "YYYY-MM-DD"}]}

## priority — judge the WORK ITSELF, not the wording
Read what the task actually is and what it affects, then ask: what breaks, and who is stuck, if this is never done?
- high: the work has real consequences — it blocks another person or another task, it puts a release, a customer, a payment or a deadline at risk, it fixes something that is broken, or the rest of the plan depends on it.
- low: optional, cosmetic or exploratory work. Nobody is waiting on it and nothing degrades if it slips.
- medium: ordinary work that moves things forward while nothing is stuck without it. This is the honest default — most tasks are medium, so do not inflate everything to high.
Urgency words ("urgent", "ASAP", "critical") and an explicit deadline are evidence, not the verdict: a genuinely consequential task with no deadline is still high, and a trivial errand someone called "urgent" is not.

## estimated_minutes (duration) — size it to what the task really demands
- Realistic focused-work minutes for one experienced person, between 15 and 960. Round to a multiple of 15.
- Let the importance of the work set the bar for "done". A high-priority task must include the time to do it PROPERLY — understanding the problem, doing the work, verifying it, getting it reviewed, and the fix-up round that follows. Under-sizing important work is the most costly mistake you can make here.
- Low-priority work gets the minimum that genuinely finishes it, and nothing more.
- Include unavoidable overhead: context loading, testing, review request.
- Be honest, not optimistic — vague or cross-team tasks take longer than they sound.

## steps
- If estimated_minutes > 120, split the task into 2-6 sequential subtask steps (short imperative phrases).
- Otherwise an empty list.

## start_date and due_date (deadline)
- Both must be on or after today's date, which is given in the user message.
- If the task already has a deadline (given as "current due_date"), keep exactly that date — it came from the meeting and outranks your judgement.
- Otherwise propose a deadline from priority and effort: high → within 2 days; medium → within 1 week; low → within 3 weeks. A task that needs many hours of work needs proportionally more calendar days.
- start_date: the day to begin, early enough that the estimated work fits before due_date at a sustainable pace (assume at most ~4 focused hours per day). For a short high-priority task, start today.
- Never set start_date after due_date.
- Skip weekends for work tasks when the deadline allows it; personal tasks may land on any day.

## Hard rules
- Triage EVERY task given; output exactly one entry per task_id, and echo task_id verbatim.
- Never invent work: judge only what the title, quote and category tell you.
"""


def triage_user(today: str, weekday: str, task_lines: str) -> str:
    return (
        f"Today is {today} ({weekday}).\n\n"
        "Tasks to triage (fields already set came from the meeting — respect them):\n"
        f"{task_lines}"
    )


def _part_note(part: int, parts: int) -> str:
    if parts <= 1:
        return ""
    return (
        f"NOTE: this is part {part} of {parts} of the transcript — it may start or end "
        "mid-discussion. Process only what is present in this part.\n\n"
    )


def summary_user(transcript: str, part: int = 1, parts: int = 1) -> str:
    return f"{_part_note(part, parts)}Transcript:\n\n{transcript}"


def summary_combine_user(partials) -> str:
    blocks = []
    for i, p in enumerate(partials, 1):
        block = f"Part {i} summary:\n{p.summary}"
        if p.decisions:
            block += "\nPart {} decisions:\n".format(i) + "\n".join(f"- {d}" for d in p.decisions)
        blocks.append(block)
    return (
        "A long transcript was summarized in parts. Merge the partial results below into ONE "
        "final result in the same JSON format: a single 3-6 sentence summary of the whole "
        "meeting, and a deduplicated merged decisions list.\n\n" + "\n\n".join(blocks)
    )


def extract_user(
    transcript: str, meeting_date: str, weekday: str, part: int = 1, parts: int = 1, roster: str = ""
) -> str:
    roster_block = (
        f"People roster (use these exact spellings for owner; fix mis-transcribed names):\n{roster}\n\n"
        if roster
        else ""
    )
    return f"{_part_note(part, parts)}{roster_block}Meeting date: {meeting_date} ({weekday})\n\nTranscript:\n\n{transcript}"


def extract_sweep_user(
    transcript: str,
    meeting_date: str,
    weekday: str,
    found_block: str,
    part: int = 1,
    parts: int = 1,
    roster: str = "",
) -> str:
    """Second pass over the same window: hunt ONLY for action items the first pass missed."""
    return (
        extract_user(transcript, meeting_date, weekday, part=part, parts=parts, roster=roster)
        + "\n\nA first pass over this exact transcript already extracted these tasks:\n"
        + (found_block or "(none)")
        + "\n\nRe-read the transcript line by line and output ONLY genuine action items that are "
        "MISSING from that list — commitments, requests, or unowned to-dos the first pass "
        "overlooked (same JSON format). Do NOT repeat or rephrase tasks already in the list, and "
        "do not lower the bar for what counts as a task. Output {\"tasks\": []} if nothing was missed."
    )
