# Suggestions — from a User's Point of View

> Written as if I'm **Anish actually using this app every day** after Phase 4. Not an architecture review — a "here's where the app annoyed me, delighted me, or left me hanging" review. Grouped by how much they'd change my daily life, with a rough effort tag.
>
> Legend: 🔥 high daily impact · ✨ delight · 🩹 papercut · effort **S/M/L**

---

## 1. The daily-driver gaps (things I'd hit on day one)

### 1.1 🔥 "Where did my day go?" — no live *now* state before Phase 6 · **M**
Phase 4 gives me a Gantt and a Today column, but nothing tells me **what to do at this exact minute**. I open the dashboard at 2:47pm and have to read the whole timeline myself. The `what_next` / **Now** button is parked in Phase 6 — but it's the single most-used thing in a planner. I'd pull a *deterministic* version forward: "current block is X, next is Y at 3:30" needs no LLM at all.

### 1.2 🔥 Marking work done is the core loop — is it one tap? · **S**
The whole value chain ends at *"did I do it?"* If checking a block done, sliding progress, or bumping a task to tomorrow takes more than one tap from the Today view, I'll stop updating it — and then every plan, stat, and estimate downstream rots. This deserves to be the most polished interaction in the app. Worth an explicit audit.

### 1.3 🔥 Replan when reality drifts · **M**
Morning auto-replan at 08:00 is great, but my day breaks at 11am when a task runs 40 min over. Right now I wait until tomorrow. I want a **"Replan rest of today"** button that repacks only *future, unpinned* blocks from now — the planner logic already exists, it just needs a "start from now" entry point.

### 1.4 🩹 Overrun handling — what happens when a block ends but I'm not done? · **S**
When I mark a block done early or it's still going, the plan should react. At minimum: a "+15 min" / "still going" nudge on the active block, and a "didn't finish → carry over" that pushes remainder into the next free slot.

---

## 2. Capture — getting meetings *in* is the top of the funnel

### 2.1 ✨ Live recording quality of life · **M**
There's a `RecordButton`, but real meetings are 45–60 min. I'd want: a running timer, pause/resume, a "recording recovered" safety net if the tab closes, and mic-device selection. If any of these are missing, long recordings are risky.

### 2.2 🔥 The 460MB Whisper cold-start is a first-run trap · **S**
My very first upload silently downloads ~460MB and looks like it hung. That first impression matters — a progress line ("downloading transcription model, one-time, 460MB") turns a scary freeze into a normal wait. Also worth: pre-pulling the model in the Docker image or a warmup on boot.

### 2.3 ✨ Paste a transcript / notes instead of audio · **S–M**
Not every meeting is recorded. Sometimes I have a Zoom/Teams/Meet transcript, or just typed notes. A **"paste text → run extraction pipeline"** path skips STT entirely and reuses everything downstream. Probably the highest value-per-effort feature not on any roadmap.

### 2.4 🩹 Batch / retry ergonomics · **S**
If I upload 3 recordings from a busy day, can I see them all processing? And when one fails at diarization, the re-run buttons exist per-stage (good) — but is there a single "retry failed stage" surfaced in the UI, or do I need the API?

---

## 3. Trust — I only believe an assistant that's honest about uncertainty

### 3.1 🔥 The maybe-mine inbox is the trust linchpin · **M**
The mine/maybe/others split is the app's best idea. But it only works if reviewing "maybe" is frictionless and I can see **why** it thinks a task is mine (`assignment_reason` exists — is it shown prominently?). A dedicated **inbox count badge** + keyboard-driven confirm/dismiss would make me actually clear it daily instead of letting maybes pile up.

### 3.2 🔥 Every task should click back to the moment it was said · **S**
`source_quote` and `segment_idx` are in the model — the killer trust feature is tapping a task and **jumping to that line in the transcript with audio playback**. "The AI says I owe Rahul a doc" → one tap → hear the 8 seconds where I agreed. Without this, I second-guess every extracted task.

### 3.3 ✨ Show pipeline confidence, not just status · **S**
"Extracted 6 tasks (2 low-confidence)" beats a silent green checkmark. Even a rough confidence surfaced from the classifier lets me know where to look.

---

## 4. Planning realism — the plan has to survive contact with a real week

### 4.1 🔥 Energy / focus awareness · **M**
A flat "4h deep-work cap" ignores that I'm sharp at 10am and mush at 4pm. Letting me tag availability windows as *deep* vs *shallow*, and tasks as *heavy* vs *light*, so the planner puts hard tasks in sharp windows, would make plans feel *mine* instead of generic.

### 4.2 🩹 Task dependencies exist in the model but do they affect scheduling? · **S–M**
`dependencies` is a column. If task B depends on A, the planner should never schedule B before A finishes. If that's not wired, it's a silent correctness gap.

### 4.3 ✨ "Protect my evenings / no weekend work" as a hard toggle · **S**
Availability rules cover this, but a one-click "I'm off this weekend, don't schedule me" (a temporary availability override / vacation mode) is something I'd use constantly and is annoying to express as rule edits.

### 4.4 🩹 Timezone & travel · **S**
Everything is `Asia/Kolkata` hardcoded in the morning job. The first time I travel, the 08:00 replan fires at the wrong local time. Worth making the app timezone a setting even if it stays single-user.

---

## 5. The chatbot — make it the app's remote control, not a sidecar

### 5.1 🔥 Natural-language edits to the plan · **M**
"Move the auth task to Thursday", "I finished the PR review", "push everything after lunch back an hour" — the chat agent already has a JSON tool protocol. The more of the app I can drive by talking, the more I'll use it. This is where the app becomes *magic* vs. *a form with an AI label*.

### 5.2 ✨ Proactive, not just reactive · **later**
The morning/evening digests (Phase 5) are the seed of this. The dream: the app messages me *"you said yes to 3 things in that meeting, 2 have no due date — want me to pick dates?"* Unprompted-but-useful is what separates an assistant from a database.

---

## 6. Data safety & operational (boring but I'll be furious if it bites me)

### 6.1 🔥 Export / backup my data · **S**
Everything I care about — transcripts, tasks, plans — lives in one Postgres + MinIO stack on my machine. One `export everything to JSON/Markdown` button (or documented `pg_dump` + MinIO copy) is my insurance. Right now, losing the volume loses my life's meeting memory.

### 6.2 🩹 Undo, especially on delete · **S**
Deleting a meeting cascades to segments, tasks, and audio (by design). One accidental click is unrecoverable. A soft-delete / trash-with-restore, or at least a typed-confirmation, would save me from myself.

### 6.3 🩹 "What is the app doing right now?" visibility · **S**
When a pipeline stalls, I can't tell if it's working or wedged without reading logs. A tiny **jobs/activity panel** (what's transcribing, what's queued, what failed) makes the background pipeline trustworthy.

---

## 7. Quick wins I'd ship this week (cheap, high delight)

- **Keyboard shortcuts** everywhere (⌘K exists — extend it: `j/k` through tasks, `e` edit, `d` done).
- **Empty states with a next action** ("No tasks yet — upload a meeting" with a button) instead of blank panels.
- **Per-task time-remaining vs due-date coloring** so at-risk items are visible without opening anything.
- **A single "Today" print/share view** I can glance at on my phone even before there's a mobile app.
- **Copy summary / decisions to clipboard** in one click (I'll paste these into messages constantly).

---

## 8. Decisions (answered 2026-07-20)

| Question | Answer | What it means for suggestions |
|----------|--------|-------------------------------|
| Scope | **Single-user forever** | Optimize hard for one person. Skip auth/sharing/multi-tenant. "Share/print" features are for *me* glancing at my phone, not collaboration. |
| Google Calendar | **Just deferred, not dead** | Keep `gcal_event_id` / `pinned` hooks intact. Calendar-dependent ideas (travel TZ, "free until next event") stay on the table; Notion is still the Phase 5 hub. |
| Build next | **All four** — live *now*+replan, paste-transcript, quote→transcript jump, export/backup | See the build-ready plan below. |
| Biggest papercut | **All of them** — capture is fragile, plan feels generic, upkeep is a chore, can't find past stuff | The app is *thin across the whole daily loop*, not broken in one place. The plan below is sequenced to thicken the loop end-to-end, not polish one corner. |

---

## 9. Build-ready plan — "Phase 4.5: Daily Driver"

A pragmatic slice *before* Phase 5/6, targeting the four picks + the four papercuts. Ordered by value-per-effort so the loop gets usable fastest. All four picks are in; nothing here needs GCal or multi-user.

### Step 1 — Paste transcript / notes → pipeline  *(picks: paste · papercut: capture)* · **S–M**
The cheapest way to kill "capture is fragile": let me bypass audio entirely.
- New `POST /meetings/text` (title + raw transcript/notes) that inserts a meeting with `status=done`, splits text into pseudo-`segments`, and jumps straight to extract → classify.
- UI: a "Paste text" tab next to Upload/Record on the dashboard.
- Reuses 100% of extraction/classification/triage downstream. No STT risk, instant result — also the fastest way to demo and test the LLM chain.

### Step 2 — Live "Now" + Replan-rest-of-today  *(picks: live now+replan · papercut: generic plan)* · **M**
Pull the *deterministic* half of Phase 6's `what_next` forward — no LLM needed.
- `GET /planner/now` → current block, next block + its start time, free-gap minutes. Pure SQL over `schedule_blocks`.
- **Now** card at the top of the Today column: "Right now: Auth integration (until 11:30) · Next: Standup 12:00".
- `POST /planner/replan?from=now` → repack only future, unpinned blocks starting at the current time. The planner already packs windows; this just changes the start boundary.
- Active-block quick actions: **Done**, **+15 min**, **Carry over** (push remainder to next free slot). Directly addresses §1.4.

### Step 3 — Quote → transcript jump + audio  *(picks: trust jump · papercut: can't find / upkeep)* · **S–M**
Make every extracted task provably real.
- `source_quote` + `segment_idx` are already stored — wire a task row → open the meeting at that segment, highlighted.
- Add an audio `<audio>` element seekable to `segments.start_sec` (audio's in MinIO; stream via a range-supporting `GET /meetings/{id}/audio`).
- Surface `assignment_reason` inline on maybe-mine cards so I see *why* before I confirm. Turns the inbox from a chore into a two-second glance.

### Step 4 — Export / backup  *(picks: export · papercut: data safety)* · **S**
Insurance against losing the whole Postgres+MinIO volume.
- `GET /export` → a zip: `meetings.json`, `tasks.json`, `plan.json`, plus per-meeting `*.md` (summary + decisions + transcript) for human-readable archives.
- Optional: include audio files, or a documented `pg_dump` + `mc cp` runbook for the heavy path.
- Settings button + a note in the README. Low effort, high peace-of-mind.

### Then, upkeep polish  *(papercut: manual upkeep)* — fold in from §7 · **S each**
One-tap done from Today, keyboard confirm/dismiss on the inbox, at-risk color coding, empty states with a next action. Small individually; together they're the difference between a plan I maintain and one I abandon.

**Sequencing rationale:** Step 1 makes it trivial to get data *in* for testing everything else. Step 2 makes the app worth opening at 2:47pm. Step 3 makes me *trust* what it extracted. Step 4 makes me unafraid to rely on it. That's the full loop — capture → act → trust → keep — thickened in one pass.
