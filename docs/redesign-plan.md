# PeopleOS Convergence — Self Planner Frontend Redesign (v2)

## Goal
Bring the Self Planner UI to the visual quality of the **PeopleOS** reference
screenshot: a floating violet-tinted dark shell, an inset rounded sidebar with
grouped nav and a real active-state treatment, a top bar that carries context
(search, notifications, account, identity) instead of just a date, and list
views that read as *records* — avatar + two-line identity, mono code chip,
dot status pill — rather than as a spreadsheet.

This is a **convergence pass on the shipped shell**, not a rebuild. v1 of this
plan (glass-dark shell, Sidebar/TopBar/⌘K search, Space Grotesk + Inter, light
theme, shimmer states) is **shipped**; a later density pass then flattened the
glass into an IDE-like flat system. v2 keeps the density win and re-adds the
polish the reference has and we lost.

Reference: PeopleOS employees list (dark, violet accent, 1920×1080).

---

## What exists today (read before changing anything)

| Piece | File | State |
|---|---|---|
| Token system | [globals.css:11-64](frontend/src/app/globals.css#L11-L64) | Flat zinc/slate, muted indigo `#7c85f0`, no glow, `--glass-shadow` is a 1px hairline |
| Shell grid | [Shell.tsx](frontend/src/components/Shell.tsx) | flex: `aside.sidebar` + `.content` — drawer + focus trap already correct |
| Sidebar | [Sidebar.tsx](frontend/src/components/Sidebar.tsx) | 216px flush panel, 3 groups, inline SVG icons, theme toggle, user card |
| Top bar | [TopBar.tsx](frontend/src/components/TopBar.tsx) | title · ⌘K search · date. Search works (tasks+meetings, keyboard nav) |
| Type | [layout.tsx](frontend/src/app/layout.tsx) | Space Grotesk display + Inter body via next/font — done |
| Page header | [globals.css:2442-2484](frontend/src/app/globals.css#L2442-L2484) | Title/subtitle grid + right action slot — structurally right |
| Task table | [TaskTable.tsx](frontend/src/components/TaskTable.tsx) | Dense, zebra-striped, sticky header, inline edit |
| Filters | [tasks/page.tsx:35-42](frontend/src/app/tasks/page.tsx#L35-L42) | Bare `<select>` in a flex row |

**Reuse, don't replace:** Shell drawer/focus-trap, TopBar search logic, Sidebar
group data + icon set, page-header grid, inline-edit cells, MiniCalendar,
TodayColumn, theme persistence script.

---

## Gap analysis — reference vs. shipped

| # | Reference does | We do | Delta |
|---|---|---|---|
| G1 | Sidebar is an **inset floating panel** (rounded 16px, margin from viewport edge, own border) | Flush column, `border-right` only | Shell padding + sidebar radius |
| G2 | Active row = tinted fill **+ 1px violet border + rounded rect + right-edge dot** | `accent-soft` fill + `inset 2px` left bar | Restyle `.sb-row.active` |
| G3 | Sidebar has its **own search field** under the logo, plus a collapse toggle | Neither | Add collapse toggle; skip 2nd search (we have ⌘K) |
| G4 | Logo mark is a gradient rounded-square with product name + eyebrow subtitle | Same — already matches | ✅ none |
| G5 | Footer = light-mode row + user card **with a role badge chip** | User card, no badge | Add `.sb-role` chip |
| G6 | Top-right cluster: context card, icon buttons, **bell with count badge**, avatar + name | Date string only | Rebuild right cluster |
| G7 | Search pill is **centered**, wide, with an inline `⌘K` key chip | Left-ish, hint baked into placeholder text | Center + real `<kbd>` chip |
| G8 | Page header: 2rem title, count subtitle, **outline secondary + violet primary pill** buttons | Title/subtitle right, unstyled buttons | Button variants |
| G9 | Filter bar: rounded controls + **segmented List/Grid toggle** | Bare selects | `.filter-bar` + `.segmented` |
| G10 | Rows: **avatar circle w/ initials (deterministic hue)**, two-line identity, mono code chip, **dot status pill**, hover row actions | Zebra rows, text-only, uppercase badges | Record-row treatment |
| G11 | Accent is a **saturated violet** with gradient on the primary button | Muted indigo, flat fill | Retune accent tokens |
| G12 | Canvas carries a faint violet tint; panels sit ~1 step lighter | Neutral zinc, zero hue | Add hue to bg/surface ramp |

---

## Design tokens (v2 — retuned, not replaced)

Same variable names, same two-theme structure. Only values change, so every
existing rule inherits the new look for free.

```
--bg          #0a0b12   (violet-leaning near-black; was #0b0e14)
--glow-a      radial rgba(124,92,255,0.10) top-left    (was transparent)
--glow-b      radial rgba(56,132,255,0.05) bottom-right
--surface     #14151f   panel
--surface-2   #1c1e2b   input / hover / raised
--border      #272a3a   hairline   --border-strong #3a3e52
--text        #e8eaf2   --text-dim #989db0   --text-faint #6a6f85
--accent      #7c5cff   --accent-hover #6a49f2   --accent-soft rgba(124,92,255,0.16)
--accent-grad linear-gradient(135deg,#8b6cff,#6a49f2)   ← primary buttons only
--radius 10px   --radius-sm 7px   --radius-lg 16px  (panels/sidebar)
```

Light theme: same keys, canvas `#f2f3f7`, surface `#ffffff`, accent `#6a49f2`,
borders `#dcdfe8`. Contrast floor 4.5:1 on both themes — `--text-dim` on
`--surface` is the tightest pair and must be verified.

Rules that keep the density win: no `backdrop-filter` on panels (it cost
legibility and paint time), hairline shadows only, 4/8px spacing scale,
14px base, mono for all dates/times/IDs.

---

## Component specs

### S1 — Sidebar (inset panel)
- Shell gains `padding: 10px` and `gap: 10px`; sidebar becomes
  `border-radius: var(--radius-lg)`, `border: 1px solid var(--border)`,
  `height: calc(100vh - 20px)`, `position: sticky; top: 10px`. Width 216→**240px**.
- `.sb-row.active`: `background: var(--accent-soft)`, `border: 1px solid
  color-mix(in srgb, var(--accent) 45%, transparent)`, `border-radius: var(--radius-sm)`,
  `color: var(--text)`, and an `::after` 6px violet dot pinned right. Drop the
  `inset box-shadow` bar.
- `.sb-row:hover` unchanged (surface-2 fill) — keep it cheaper than active.
- Footer user card gains `.sb-role` — uppercase 0.6rem violet-tinted chip
  ("PERSONAL"), mirroring the reference's ORG ADMIN badge.
- Collapse toggle beside the logo: sets `data-collapsed` on the shell; collapsed
  = 64px rail, icons only, labels hidden, `title` attr for a11y. Persist in
  `localStorage` next to the theme key.

### S2 — Top bar (right cluster)
Layout: `hamburger · title · [flex spacer] · search (centered, max 460px) ·
[flex spacer] · right cluster`.
- Search pill: keep all TopBar search logic. Move the hint out of the
  placeholder into a real `<kbd>⌘K</kbd>` positioned absolute-right inside the
  pill; placeholder becomes "Search tasks, meetings, commands…".
- Right cluster (new, ~4 elements, all ≥36px hit targets):
  - **Context card** — "TODAY'S PLAN / {N} blocks" mirroring the reference's
    account card; clicking routes to `/`. Pure display, no dropdown in P1.
  - **Theme toggle** icon button (moved out of the sidebar footer? **No** —
    duplicate it here is churn; keep it in the sidebar, put a *notifications*
    bell here instead).
  - **Bell** with count badge = number of overdue tasks (we already fetch tasks
    for search — reuse that payload, zero new API calls). Click → `/tasks`.
  - **Identity** — avatar circle + "Anish".
- Date line moves under the page title as a subtitle, or drops entirely
  (the dashboard hero already greets with the date).

### S3 — Buttons
Three variants, applied by class, no new deps:
- `.btn-primary` — `--accent-grad` fill, white text, `border-radius: 999px`,
  `padding: .55rem 1.1rem`, weight 600, optional leading `+` icon.
- `.btn-secondary` — transparent fill, `1px var(--border-strong)`, `--text`,
  same pill radius.
- Existing `button.ghost` / `button.mini` / `.ghost-danger` stay as-is.
Default bare `<button>` keeps today's flat accent fill so nothing regresses.

### S4 — Filter bar + segmented control
- `.filter-bar` — flex row, 10px gap, controls at `--radius-sm`, `--surface-2`
  fill, min-height 38px. Selects get a chevron via background SVG so the native
  arrow stops looking foreign in dark mode.
- `.segmented` — 2–3 button group in a `--surface-2` pill; active button gets
  `--surface` fill + `--text` + hairline. Used for the tasks page's
  **List / Board** switch (List ships; Board is out of scope, so ship the
  control only where both views exist — i.e. **defer** until a second view exists).

### S5 — Record rows (task + meeting lists)
Applies to `.mytask`, `.meeting-card`, and the `.task-table` on `/tasks`.
- `.avatar-chip` — 34px circle, initials, background hue derived from a hash of
  the assignee/title string (8 fixed hues, all ≥4.5:1 against white text).
- Two-line identity cell: title (600, `--text`) over meta (`--text-dim`, 0.78rem).
- `.code-chip` — mono, `--surface-2` fill, hairline border, `--radius-sm`,
  0.72rem. Used for task IDs and meeting dates.
- `.status-pill` — leading 6px dot + uppercase label, tinted by semantic token
  (open/violet, done/success, overdue/danger, at-risk/warn). Replaces the
  current flat `.badge` / `.prio` styling; **same class names kept** so no TSX
  churn where possible.
- Row height ~64px, `border-bottom: 1px solid var(--border)`, **zebra striping
  removed** (the reference has none and it fights the row separators), hover =
  `--row-hover`. Row actions (Edit / Open / delete) reveal on hover — the
  existing hover-reveal rule already does this for the delete button.

**Explicitly kept dense:** the `/tasks` and meeting-detail tables stay
information-dense; the record treatment applies to the *identity column and
badges*, not to row padding across every table. A 7-row HR list can afford 64px
rows; a 40-task backlog cannot.

---

## Interaction states (unchanged from v1, verify still wired)
Shimmer skeletons, designed empty states, error banners with retry, and the
motion rules (`rise-in` 200ms, `:active` 0.98 scale, `prefers-reduced-motion`
kill switch) are already in `globals.css` — this pass must not regress them.
New states needed: bell badge zero-state (no badge, not "0"), collapsed-sidebar
tooltips, and the avatar fallback when a task has no assignee (neutral chip
with a person glyph).

---

## Accessibility
- Every new tinted-on-tinted pair (status pill text on its own tint, `--text-dim`
  on `--surface-2`, violet text on `--accent-soft`) must be checked ≥4.5:1 in
  **both** themes. The violet-on-accent-soft pair is the likely failure — bump
  pill text to `--text` with a tinted dot if it misses.
- Collapsed sidebar rows need accessible names (`aria-label` / `title`), not
  just icons.
- Bell badge count needs an `aria-label` ("3 overdue tasks"), not a bare number.
- Keep `:focus-visible` 2px accent ring; pill-radius elements need
  `outline-offset: 2px` to stay legible.
- Touch targets ≥44px on mobile for the whole new top-bar cluster.

---

## NOT in scope
- No backend changes, no new routes, no new API calls (the bell reuses the
  search payload).
- No board/grid view — the segmented control ships only when a second view does.
- No per-page IA changes; pages keep their structure and copy.
- No `backdrop-filter` revival — the density pass removed it deliberately.
- Gantt internals ([gantt.css](frontend/src/app/gantt/gantt.css)) get token
  updates only, not a layout rework.

---

## Implementation tasks

- [x] **T1 (P1, ~30min)** — Tokens: retune `:root` + `[data-theme=light]` values per the block above; add `--accent-grad`, `--radius-lg`, restore `--glow-a/b` and wire the body radial gradient.
  - Files: [globals.css](frontend/src/app/globals.css)
  - Verify: every page renders unchanged in *structure*, warmer in *hue*; no hardcoded old hex left (`grep -n '7c85f0\|0b0e14' frontend/src`)
- [x] **T2 (P1, ~35min)** — Sidebar panel: inset shell padding, 240px + `--radius-lg`, new `.sb-row.active` (border + right dot), `.sb-role` badge, collapse toggle + persisted `data-collapsed` rail.
  - Files: [Sidebar.tsx](frontend/src/components/Sidebar.tsx), [Shell.tsx](frontend/src/components/Shell.tsx), globals.css
  - Verify: 1440px expanded + collapsed, 375px drawer still traps focus and closes on Esc
- [x] **T3 (P1, ~40min)** — Top bar cluster: centered search + `<kbd>` chip, context card, overdue bell (reusing the search task payload), identity block; retire the bare date.
  - Files: [TopBar.tsx](frontend/src/components/TopBar.tsx), globals.css
  - Verify: ⌘K still focuses; bell count matches `/tasks` overdue count; no extra network request in devtools
- [x] **T4 (P2, ~20min)** — Buttons: `.btn-primary` / `.btn-secondary`; apply to page-header actions on meetings, tasks, settings.
  - Files: globals.css, `frontend/src/app/**/page.tsx`
  - Verify: primary reads as the single loudest control per screen
- [x] **T5 (P2, ~25min)** — Record rows: `.avatar-chip` (hashed hue), `.code-chip`, `.status-pill` (dot), drop zebra, hover-reveal actions.
  - Files: [TaskTable.tsx](frontend/src/components/TaskTable.tsx), [MeetingCard.tsx](frontend/src/components/MeetingCard.tsx), globals.css
  - Verify: dashboard + meetings + tasks screenshots vs. reference
- [x] **T6 (P2, ~15min)** — Filter bar: `.filter-bar` wrapper, styled selects with custom chevron.
  - Files: [tasks/page.tsx](frontend/src/app/tasks/page.tsx), [meetings/page.tsx](frontend/src/app/meetings/page.tsx), globals.css
  - Verify: controls align on one baseline, 38px min height
- [x] **T7 (P1, ~10min)** — Contrast audit across both themes for every new tinted pair; fix failures before merge.
  - Files: globals.css
  - Verify: each pair ≥4.5:1 (≥3:1 for the ≥18px page title)
- [x] **T8 (P1, ~10min)** — Rewrite [DESIGN.md](frontend/DESIGN.md) to the v2 token table + component specs so it matches shipped CSS.
  - Files: frontend/DESIGN.md
  - Verify: every token in DESIGN.md exists verbatim in globals.css

**Order:** T1 → T2 → T3 → (T4, T5, T6 in any order) → T7 → T8.
T1 is load-bearing; everything after it assumes the retuned ramp.

---

## Approved references

| Screen | Reference | Direction | Notes |
|---|---|---|---|
| Employees list (PeopleOS) | user-supplied screenshot, 2026-07-21 | Violet dark, inset sidebar, record rows | Single `#7c5cff` accent; gradient reserved for primary buttons; no glass blur; density preserved on our long tables |

## Review report

| Review | Trigger | Runs | Status | Findings |
|---|---|---|---|---|
| CEO Review | `/plan-ceo-review` | 0 | — | — |
| Codex Review | `/codex review` | 0 | — | — |
| Eng Review | `/plan-eng-review` | 0 | — | not required — CSS + presentational components only |
| Design Review | `/plan-design-review` | 0 | — | **recommended before T1** |
| DX Review | `/plan-devex-review` | 0 | — | n/a |

- **UNRESOLVED:** 0 — both closed during implementation. (a) The segmented
  control **ships** on Gantt, where Day/Week/Month are three views that genuinely
  exist; it is still not built for a List/Board switch that has no second view.
  (b) The theme toggle stays **sidebar-only**; the top-bar slot went to the
  overdue bell instead.
- **VERDICT:** SHIPPED — T1–T8 implemented and verified. See "Deltas from plan"
  below for the four places the build diverged from this document.

---

## Deltas from plan (what actually shipped, 2026-07-21)

Recorded because the plan above is now a historical document, and these are the
places it is wrong.

1. **Glass, not flat.** The plan said "NOT in scope: no `backdrop-filter`
   revival." The user then supplied light + dark PeopleOS screenshots and asked
   for the glassy look directly. Panels are now `rgba(255,255,255,0.055)` over
   `blur(22px) saturate(150%)`, with an opaque `@supports` fallback. Density,
   the thing the earlier pass was protecting, is preserved: 14px base, 4/8px
   scale, no extra row padding.
2. **The accent is three tokens, not one.** `#7c5cff` under white text is only
   4.35:1 — it fails AA as a button fill. One violet cannot be both a fill dark
   enough for white text and text light enough for a near-black canvas. Split
   into `--accent` (tints/dots/rings), `--accent-solid` (fills, 5.2:1) and
   `--accent-text` (coloured text, 5.8:1).
3. **Muted text runs brighter than a flat design would want.** Glass over the
   glow hotspot lifts the backdrop and eats contrast headroom, so `--text-dim`
   and `--text-faint` are set to the dimmest values that still clear 4.5:1 *at
   the hotspot*, not against flat `--bg`. Full method in `frontend/DESIGN.md`.
4. **The bell costs one request pair per navigation.** The plan claimed "zero
   new API calls". True in the sense that it reuses the search index and adds no
   new endpoint — but that index is now loaded on mount rather than on first
   search focus, so `listTasks` + `listMeetings` fire once per navigation
   instead of once per session. The count would otherwise be blank until you
   opened search, which makes the badge useless.

### Decisions taken during implementation
| # | Decision | Chosen | Why |
|---|---|---|---|
| D1 | Avatar chips | Multi-person surfaces only | `/tasks` is filtered to `assignment=mine`; identical chips on every row are decoration. `TaskTable` turns them on only when `distinctOwners > 1`. |
| D2 | Top-bar right cluster | Overdue bell + identity | The reference's account card exists because PeopleOS is multi-tenant. Self Planner has one user, so the card had nothing true to say. |
| D3 | Primary buttons | Flat violet | App-UI rules discourage decorative gradients, and violet gradients are the most recognisable AI-generated tell. |

### Bugs found and fixed during visual verification
- `button:hover:not(:disabled)` (specificity 0,2,1) outranked `.theme-toggle:hover`
  (0,2,0), so the theme toggle rendered as a solid violet button on hover in both
  themes. Fixed by raising specificity; same fix applied to `.hamburger`.
- The collapsed-rail rule `.sb-logo > div { display: none }` also hid
  `.sb-logo-mark` and `.sb-avatar` — both are plain divs and direct children.
  Scoped with `:not()`.
- `--border` is a white glass edge, so mono chips and the ⌘K key chip had no
  visible outline on light-theme panels. Chips now use `--border-strong`.
- The sidebar tagline wrapped to two lines at 240px. Set to `nowrap`.

### Not verified
The record-row treatment (`.code-chip`, `.status-pill`, `.avatar-chip`) was
verified against a static harness built from the compiled CSS, not against live
data — the backend was unreachable during this session. The task table, meeting
list and dashboard rows should be re-checked once the backend is running.
