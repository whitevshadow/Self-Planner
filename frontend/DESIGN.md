---
version: 1.0
name: Self Planner — Glass Dark
description: A modern glassmorphism design system for Self Planner. Deep navy canvas with a violet radial glow, translucent frosted panels defined by hairline borders and backdrop blur, a single violet accent, Space Grotesk display type over Inter body. Dark-first with a frosted-daylight light theme on the same tokens.

colors:
  # Canvas + glow
  bg: "#0a0d16"
  glow-a: "rgba(124, 92, 255, 0.16)"   # violet, top-left
  glow-b: "rgba(56, 189, 248, 0.07)"    # sky, bottom-right
  # Glass surfaces
  surface: "rgba(255, 255, 255, 0.045)" # panel fill
  surface-2: "rgba(255, 255, 255, 0.07)"
  surface-solid: "#141827"              # backdrop-filter fallback + dropdowns
  border: "rgba(255, 255, 255, 0.09)"   # glass hairline
  border-strong: "rgba(255, 255, 255, 0.16)"
  # Text
  text: "rgba(255, 255, 255, 0.92)"
  text-dim: "rgba(255, 255, 255, 0.55)"
  text-faint: "rgba(255, 255, 255, 0.35)"
  # Accent (single, structural)
  accent: "#7c5cff"
  accent-hover: "#6847f0"
  accent-soft: "rgba(124, 92, 255, 0.18)"
  # Semantic
  danger: "#ff6b6b"
  success: "#3ddc84"
  warn: "#ffb020"

typography:
  display:
    fontFamily: "Space Grotesk"
    role: "Headings h1-h3, greeting, card titles"
    weight: 700
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Inter"
    role: "Body copy, table rows, nav, meta"
    weight: 400

rounded:
  sm: 8px
  md: 11px
  lg: 16px      # --radius, the panel default
  full: 9999px

spacing:
  base: 8px

components:
  glass-panel:
    background: "{colors.surface}"
    border: "1px solid {colors.border}"
    borderRadius: "{rounded.lg}"
    backdropFilter: "blur(18px)"
    boxShadow: "0 8px 32px rgba(0,0,0,0.25)"
  sidebar:
    width: 250px
    background: "{colors.surface}"
    backdropFilter: "blur(20px)"
    activeRow: "{colors.accent-soft} fill + 2px inset {colors.accent} left indicator"
  accent-button:
    background: "{colors.accent}"
    hover: "{colors.accent-hover}"
    press: "scale(0.98)"
    borderRadius: "{rounded.sm}"
---

## Overview

Self Planner is a calm, focused workspace — a personal planner, not a marketing
site. The design is **glassmorphism on a dark canvas**: a deep navy field
(`#0a0d16`) lit by a soft violet radial glow in the top-left and a faint sky glow
bottom-right, with content sitting on **translucent frosted-glass panels** —
low-alpha white fills, 1px hairline borders, and an 18px backdrop blur that lets
the glow bleed through. One violet accent (`#7c5cff`) does all the work: active
nav, primary buttons, calendar "today", focus rings. Everything else is white at
graded opacity.

Type pairs **Space Grotesk** (geometric, slightly technical) for headings with
**Inter** for body — the display face is the "this was designed" signal; Inter
keeps long lists readable. Both self-host via `next/font` so the offline Docker
build has no runtime font fetch.

The reference is the calm end of the glass spectrum — Linear, Raycast, the PeopleOS
dashboard — not neon cyberpunk. Depth comes from blur and hairlines, never heavy
drop shadows.

**Key characteristics:**
- Deep navy canvas `{colors.bg}` with fixed violet + sky radial glows
- Frosted-glass panels: ≤6% white fill, hairline border, `blur(18px)`, 16px radius
- One structural accent — violet `{colors.accent}` — for every action and active state
- Space Grotesk display over Inter body, self-hosted
- Fixed 250px glass sidebar (desktop) → hamburger slide-over drawer (≤768px)
- Dark-first; light theme is a frosted-daylight override on the same variables

## Layout

**App shell.** A fixed 250px glass sidebar holds the logo, three eyebrow-labelled
nav groups (OVERVIEW / PLANNING / SETTINGS) with inline SVG line icons, a theme
toggle, and a user card pinned to the bottom. The content column has a sticky top
bar (page title · ⌘K search pill · date) over a centered 1120px main area.

**Mobile (≤768px).** Sidebar hides; a hamburger in the top bar opens a focus-trapped
glass drawer (Esc / backdrop-tap closes). Content goes full-width.

**Dashboard grid.** Two columns: primary task list (high-priority spotlight card +
"everything else") on the left, mini calendar + Today schedule on the right.
Collapses to one column at 900px.

## Color usage

- **Accent is precious.** `{colors.accent}` paints active nav, primary buttons,
  the calendar's "today", `:focus-visible` rings, and monospace time labels. Never
  decorative.
- **Hierarchy by opacity, not hue.** Primary text 92%, secondary 55%, faint 35%.
- **Semantic hairlines.** Overdue/at-risk items signal with a colored border, not
  a filled background — keeps the glass calm.
- **Glass fill stays ≤6%** on the dark canvas so body text clears 4.5:1 contrast.

## Motion
- Entrance: `main` children fade up 8px over 200ms per navigation.
- Hover: panel borders brighten toward `{colors.border-strong}`.
- Press: buttons `scale(0.98)`.
- All motion disabled under `prefers-reduced-motion`.

## Accessibility
- Text on glass ≥ 4.5:1 (guaranteed by the ≤6% panel alpha over `#0a0d16`).
- `:focus-visible` = 2px violet ring, 2px offset, on every interactive element.
- Touch targets ≥ 44px on mobile (nav rows, hamburger, buttons).
- Mobile drawer is `role="dialog" aria-modal` with a focus trap.
- `@supports not (backdrop-filter)` → panels fall back to solid `#141827`.

## Light theme
`[data-theme="light"]` overrides the same CSS variables: canvas `#eef0f5`, glass
`rgba(255,255,255,0.6)`, ink text, darker accent `#6847f0` for contrast. Toggled
from the sidebar footer; persisted in `localStorage` and applied pre-paint via an
inline script to avoid a flash. It is a genuine second surface but deliberately
secondary — the app is designed dark-first.

## Do's and Don'ts

### Do
- Reserve `{colors.accent}` for actions, active state, and focus — nothing else.
- Build every card from the `glass-panel` recipe so all surfaces read as one system.
- Set headings in Space Grotesk with its negative tracking; body in Inter at 400.
- Signal danger/warn with a colored hairline border, not a filled panel.
- Keep the glow fixed (`background-attachment: fixed`) so it anchors the canvas.

### Don't
- Don't add a second accent hue — violet is the only structural color.
- Don't raise glass fill above ~8% — text contrast breaks and the frost turns milky.
- Don't use heavy drop shadows; depth is blur + hairline.
- Don't put emoji in the chrome (nav, buttons) — inline SVG icons only.
- Don't ship dead controls; the ⌘K search filters real loaded tasks & meetings.
