---
version: 2.0
name: Self Planner — Glass
description: >
  Translucent panels floating over a glowing canvas. Deep near-black with a violet
  radial glow top-left, indigo upper-right and a teal wash at the bottom; panels are
  low-alpha white over a 30px backdrop blur, defined by hairline borders rather than
  by fills. One saturated violet accent, split into fill/text/tint tokens so every
  text pair clears WCAG AA. Dense 4/8px spacing is preserved — glass is the surface
  treatment, not an excuse for air. Dark-first with a pale-lavender light theme on
  the same variables.
source_of_truth: src/app/globals.css
reference: PeopleOS (user-supplied screenshots, 2026-07-21)

# ─────────────────────────────────────────────────────────────────────
# THE ONE RULE THAT DRIVES EVERYTHING ELSE
# On glass, the backdrop behind text is not a constant — it is whatever the
# glow puts there. Every muted colour below is the DIMMEST value that still
# clears 4.5:1 at the glow's hottest point, computed by compositing
# panel-alpha over glow-peak over canvas. Do not dim them "because they look
# too bright on a flat swatch". They are not on a flat swatch.
# Verify with the method in ## contrast before changing any of them.
# ─────────────────────────────────────────────────────────────────────

colors:
  dark:
    bg: "#07070f"                                  # near-black; the glow does the colouring
    glow-a: "rgba(124, 92, 255, 0.24)"             # violet, top-left
    glow-b: "rgba(45, 212, 191, 0.12)"             # teal, bottom
    glow-c: "rgba(96, 84, 220, 0.19)"              # indigo, upper-right
    surface: "rgba(255, 255, 255, 0.045)"          # glass panel fill — thin, so the glow reads through
    surface-2: "rgba(255, 255, 255, 0.05)"         # input / hover / raised (stacks ON the sheen — see ## contrast)
    surface-solid: "rgba(22, 23, 32, 0.86)"        # dropdowns over page content
    surface-opaque: "#15161f"                      # @supports fallback
    row-hover: "rgba(255, 255, 255, 0.055)"
    border: "rgba(255, 255, 255, 0.1)"             # glass edge
    border-strong: "rgba(255, 255, 255, 0.2)"      # chips, outlines needing a real edge
    text: "#eef0f7"
    text-dim: "#bcc0d0"
    text-faint: "#a6abbd"
    accent: "#7c5cff"                              # tints, borders, dots, rings — NEVER text, never a fill under text
    accent-solid: "#7053e5"                        # fills that carry white text (5.2:1)
    accent-hover: "#5f43d4"
    accent-text: "#b3a2ff"                         # accent-coloured TEXT (5.8:1 at the hotspot)
    accent-soft: "rgba(124, 92, 255, 0.16)"
    on-accent: "#ffffff"
    danger: "#ff7b85"
    success: "#4fd37c"
    warn: "#f0b64a"
  light:
    bg: "#eef0fb"                                  # pale lavender
    glow-a: "rgba(139, 124, 255, 0.3)"
    glow-b: "rgba(120, 165, 255, 0.28)"
    glow-c: "rgba(160, 150, 255, 0.22)"
    surface: "rgba(255, 255, 255, 0.55)"
    surface-2: "rgba(255, 255, 255, 0.8)"
    surface-solid: "rgba(255, 255, 255, 0.94)"
    surface-opaque: "#ffffff"
    row-hover: "rgba(255, 255, 255, 0.75)"
    border: "rgba(255, 255, 255, 0.85)"
    border-strong: "rgba(23, 26, 48, 0.14)"
    text: "#141631"
    text-dim: "#4d5270"
    text-faint: "#585e79"
    accent: "#6a49f2"
    accent-solid: "#6a49f2"
    accent-hover: "#5838e0"
    accent-text: "#5836e0"                         # darker than the fill: it sits on the violet tint
    accent-soft: "rgba(106, 73, 242, 0.12)"
    on-accent: "#ffffff"
    danger: "#c92b3c"
    success: "#10804a"
    warn: "#8f5f04"

# Why the accent is three tokens, not one:
# a single violet cannot simultaneously be (a) a fill dark enough to carry white
# text and (b) text light enough to read on a near-black canvas. Splitting it is
# what lets the brand hue stay #7c5cff while both uses pass AA.
accent-usage:
  fill-under-white-text: accent-solid    # buttons, avatars, logo mark, today pill, sent chat bubbles
  coloured-text: accent-text             # links, timestamps, .meeting-link, active nav icon
  tint-border-dot-ring: accent           # .sb-row.active border, status dots, focus ring, progress fill

typography:
  display:
    fontFamily: "Space Grotesk"          # next/font, self-hosted at runtime
    role: "h1-h3, greeting, card titles"
    weight: 700
    letterSpacing: "-0.02em"
  body:
    fontFamily: "Inter"
    role: "Body copy, table rows, nav, meta"
    size: 14px
    lineHeight: 1.45
  mono:
    fontFamily: "ui-monospace, Cascadia Code, SF Mono, Consolas"
    role: "Dates, times, durations, IDs — anything that should align in a column"

blur: 30px                               # --blur; applied with saturate(165%)
radius:
  sm: 11px                               # --radius-sm: inputs, small buttons, chips
  md: 18px                               # --radius, the panel default
  lg: 26px                               # --radius-lg: sidebar, appbar, full-bleed panels
  full: 9999px                           # buttons, pills, segmented control
  # Every non-micro radius in globals.css resolves to one of these. Only the
  # progress track (3px) and <kbd> (4px) still carry raw px.
spacing:
  base: 8px                              # 4/8px scale
shadow:
  dark: "0 10px 40px rgba(0, 0, 0, 0.34)"
  light: "0 10px 40px rgba(40, 45, 100, 0.13)"
  accent-glow: "0 6px 20px {accent}@38% — depth on the primary button; NOT a gradient"
sheen:
  dark: "linear-gradient(157deg, rgba(255,255,255,0.05), transparent 58%)"
  light: "linear-gradient(157deg, rgba(255,255,255,0.55), transparent 58%)"
  edge-hi: "inset 0 1px 0 rgba(255,255,255, .14 dark / .9 light) — the lit top edge"

components:
  glass-panel:
    applies-to: >
      .upload-card .record-card .meeting-card .summary-card .task-table-wrap
      .today-col .mini-cal .hp-section .inbox .speaker-bar .gantt-wrap
      .tt-preview .new-meeting .transcript .rec-step-guide .mytask .now-card
      .block .empty-state .error-banner .notice-banner .bulk-bar
      .chat-suggestion .search-pop .sidebar .appbar
    background: "{surface}"
    border: "1px solid {border}"
    borderRadius: "{radius.md}"
    backdropFilter: "blur({blur}) saturate(165%)"
    boxShadow: "{shadow}, {sheen.edge-hi}"
    backgroundImage: "{sheen}"
    fallback: "@supports not (backdrop-filter) -> background: {surface-opaque}"
  shell:
    layout: "flex; padding 10px; gap 10px — panels are INSET, never flush to the viewport"
    sidebar: { width: 240px, collapsed: 64px, radius: "{radius.lg}", sticky: true }
    appbar: "rounded panel, sticky, own blur; hamburger . title . search (centred, max 460px) . bell . identity"
  sidebar-row:
    rest: "color {text-dim}; 1px transparent border reserved so :active never shifts layout"
    hover: "background {surface-2}; color {text}"
    active: "background {accent-soft}; border 1px {accent}@45%; ::after 6px {accent} dot pinned right; icon {accent-text}"
  buttons:
    primary: "{accent-solid} fill, {on-accent} text, pill radius, 38px min — FLAT, never a gradient"
    secondary: "transparent, 1px {border-strong}, pill radius"
    ghost-mini-ghostdanger: "unchanged from v1"
    specificity-trap: >
      `button:hover:not(:disabled)` has specificity (0,2,1). Any transparent
      button MUST out-specify it (e.g. `button.theme-toggle:hover:not(:disabled)`)
      or it turns into a solid violet button on hover.
  record-row:
    code-chip: "mono, {surface-2} fill, 1px {border-strong}, radius.sm — IDs, dates, durations"
    status-pill: "6px leading dot carries the semantic colour; the LABEL stays {text} so every pill clears 4.5:1"
    avatar-chip: "30px circle, initials, 1 of 8 fixed hues by stable hash; all >=5.1:1 under white glyphs"
    rows: "hairline bottom border, hover = {row-hover}. NO zebra striping — it fights the borders."
  segmented:
    use: "only where multiple views genuinely exist (Gantt Day/Week/Month)"
    style: "{surface-2} pill track; active button gets {surface} fill + shadow"
  filter-bar:
    controls: >
      {surface-2}, radius.sm, 38px min-height; selects use a custom SVG chevron
      (the native dark-mode arrow renders light-on-light on Windows)

motion:
  entrance: "rise-in — fade up 8px / 200ms, once per navigation"
  press: "scale(0.98) on :active"
  hover: "border-colour lifts to {border-strong}; never the fill — keeps text contrast identical between rest and hover"
  processing: "status dot pulses (now-pulse 2s) so 'still working' is legible without reading"
  reduced-motion: "prefers-reduced-motion kills all animation and transition"

contrast:
  standard: "WCAG AA — 4.5:1 for text, 3:1 for UI graphics"
  method: >
    Glass makes contrast positional. Do not sample a flat token. Composite
    panel-alpha OVER glow-peak OVER canvas, then measure text against THAT.
    Check three backdrops per theme (plain canvas, glow-a peak, glow-b peak)
    and four surfaces per backdrop: surface, surface + sheen, surface-2 nested
    on the sheen, and accent-soft over the sheen. The sheen is the trap — white
    layers COMPOUND, so panel(4.5%) + sheen(5%) + surface-2(5%) is ~14%
    cumulative white, and that stack is what binds the muted ramp.
  status: "All pairs pass in both themes at every glow position (verified 2026-07-21)"
  tightest-pairs:
    - "dark text-faint on surface-2 stacked on the sheen over the violet hotspot — 4.51:1"
    - "light text-faint on accent-soft — 4.65:1"
    - "light accent-text on accent-soft — 5.07:1"
  a11y-invariants:
    - "Collapsed sidebar rows keep aria-label + title — icons alone are not accessible names"
    - "Bell badge is absent at zero (never '0') and carries an aria-label naming the count"
    - "Touch targets >=44px below 768px"
    - ":focus-visible 2px accent ring, outline-offset 2px so it clears pill radii"

not-in-this-system:
  - "Decorative gradients on controls — this is app UI; the accent alone carries hierarchy, and violet gradients are the top AI-slop tell"
  - "Zebra striping"
  - "Avatars on single-owner lists — an avatar that is always the same avatar is decoration, not identity"
  - "A tenancy/context card in the top bar — Self Planner has one user and no tenancy"
