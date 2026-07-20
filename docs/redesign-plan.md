# Glassy Dark Redesign — Self Planner

## Goal
Rewrite the frontend look to a modern glassmorphism UI in the style of the
PeopleOS reference: fixed left sidebar navigation, deep navy canvas with a
violet radial glow, translucent frosted-glass panels, one violet accent.
Approved visual reference: **Variant A** (`~/.gstack/projects/self_planner/designs/glass-dashboard-20260713/variant-A.png`).

## Design Tokens (approved — Variant A)
- Canvas: `#0a0d16`; glow: radial violet `rgba(124,92,255,0.16)` top-left + faint sky bottom-right
- Glass panel: `rgba(255,255,255,0.045)` fill, `1px rgba(255,255,255,0.09)` border,
  `backdrop-filter: blur(18px)`, radius 16px, shadow `0 8px 32px rgba(0,0,0,0.25)`
- Accent (single): `#7c5cff`, hover `#6847f0`; text: `rgba(255,255,255,0.92)` primary,
  `rgba(255,255,255,0.55)` muted, `rgba(255,255,255,0.35)` faint
- Semantic: danger `#ff6b6b`, warn `#ffb020`, success `#3ddc84`
- Type: **Space Grotesk** (headings, via next/font) + **Inter** (body) — D5/3A
- Light theme (D7/5B): `[data-theme="light"]` overrides — canvas `#eef0f5`, glass
  `rgba(255,255,255,0.6)`, ink text, same accent; toggle pinned in sidebar footer

## App Shell
- `Sidebar.tsx` replaces top NavBar: logo block, eyebrow groups
  (OVERVIEW: Dashboard, Meetings, All Tasks · PLANNING: Chat, Gantt ·
  SETTINGS: People, Availability), inline SVG line icons (no emoji — Pass 4),
  active row = violet 18% fill + 2px left indicator, theme toggle + user card bottom.
- Top bar: page title, center ⌘K search pill, date at right.
- Mobile ≤768px (D6/4B): sidebar hidden; hamburger in top bar opens a slide-over
  glass drawer (focus-trapped, Esc/backdrop closes); content full-width.

## Search (D3/1A)
Client-side: Ctrl/⌘K focuses pill; filters open tasks + meetings by title;
grouped dropdown (Tasks / Meetings) with keyboard nav; empty: "No matches for
'{q}'"; scope hint "tasks & meetings" as placeholder.

## Interaction States (D4/2A)
| Feature | Loading | Empty | Error | Success | Partial |
|---|---|---|---|---|---|
| Dashboard tasks | 3 shimmer glass rows | "All clear ✨" + Record CTA | glass banner, red hairline, retry | rows | overdue = red hairline |
| Mini calendar | instant | n/a | n/a | due-date dots | — |
| Today column | shimmer blocks | "Nothing scheduled" + Replan | warn chips | blocks | at-risk = amber hairline |
| Meetings | shimmer cards | "No meetings yet" + record/upload CTA | banner + Retry | cards | processing = violet pulse badge |
| Search | — | "No matches for '{q}'" | n/a | grouped dropdown | — |
| Chat | typing dots | starter suggestion chips | inline retry | messages | tool chips |

## Motion
Entrance: content fades up 8px/200ms once per navigation; hover: cards lift
border to 14% white; press: 0.98 scale on buttons; all disabled under
`prefers-reduced-motion`.

## Accessibility (Pass 6)
Text on glass ≥ 4.5:1 (panel alpha ≤6% guarantees this on #0a0d16);
`:focus-visible` 2px violet ring; touch targets ≥44px on mobile; drawer is a
`dialog` with focus trap; `backdrop-filter` fallback: solid `#141827` panels
via `@supports not`.

## User Journey (Pass 3)
Land → greeting orients (time, name) → status line points attention →
high-priority card is the single loudest element → Today column converts
attention to action. First-run: every empty state teaches the loop
(record → tasks → plan).

## NOT in scope
- Transcript/chat content in ⌘K search (P3 TODO) — client lists only
- New features/routes/backend changes — pure reskin + shell + search
- Per-page IA changes beyond shell adoption — pages keep their structures

## What already exists (reuse)
Single-file CSS variable theming; dashboard grid; MiniCalendar; TodayColumn;
TaskTable; page structures; formatDue/dates utils.

## Implementation Tasks
- [ ] **T1 (P1, human: ~1d / CC: ~40min)** — globals.css — replace tokens with glass-dark system + light overrides, glass utilities, shimmer, motion, focus rings
  - Surfaced by: Pass 5 — approved Variant A tokens
  - Files: frontend/src/app/globals.css
  - Verify: screenshot dashboard vs variant-A.png
- [ ] **T2 (P1, human: ~1d / CC: ~30min)** — Sidebar — new Sidebar.tsx (SVG icons, groups, active state, user card, theme toggle), mobile drawer; layout.tsx shell grid; remove NavBar
  - Surfaced by: Pass 1 + D6/4B
  - Files: frontend/src/components/Sidebar.tsx, frontend/src/app/layout.tsx
  - Verify: browse responsive screenshots (375px drawer, 1440px fixed)
- [ ] **T3 (P1, human: ~2h / CC: ~15min)** — Typography — next/font Space Grotesk + Inter wired to CSS vars
  - Surfaced by: Pass 4 — D5/3A
  - Files: frontend/src/app/layout.tsx, globals.css
  - Verify: headings render Space Grotesk offline
- [ ] **T4 (P2, human: ~2h / CC: ~20min)** — Search — ⌘K client-side task+meeting search in top bar
  - Surfaced by: Pass 1 — D3/1A
  - Files: frontend/src/components/TopBar.tsx (new)
  - Verify: type query → grouped results navigate
- [ ] **T5 (P2, human: ~3h / CC: ~25min)** — States — shimmer skeletons + designed empty states per table
  - Surfaced by: Pass 2 — D4/2A
  - Files: page.tsx files, globals.css
  - Verify: throttle network, check each screen's empty/loading
- [ ] **T6 (P1, human: ~1h / CC: ~10min)** — DESIGN.md — rewrite to glass system tokens
  - Surfaced by: Pass 5
  - Files: frontend/DESIGN.md
  - Verify: tokens match shipped globals.css

## Approved Mockups

| Screen/Section | Mockup Path | Direction | Notes |
|----------------|-------------|-----------|-------|
| Dashboard | ~/.gstack/projects/self_planner/designs/glass-dashboard-20260713/variant-A.png | Violet PeopleOS glass | Single #7c5cff accent; panel alpha ≤6%; no emoji icons; hamburger drawer on mobile; light-theme variant via sidebar toggle |

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 0 | — | — |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | CLEAR (FULL) | score: 4/10 → 9/10, 5 decisions |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **UNRESOLVED:** 0
- **VERDICT:** DESIGN CLEARED — plan is design-complete; eng review not run (frontend reskin, no architecture change)
