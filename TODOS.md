# TODOS

## Search transcripts and chat history from ⌘K
- **What:** Server-side search endpoint (Postgres full-text or pgvector, already in the stack) wired into the ⌘K search dropdown as a third result group.
- **Why:** "What did we say about X?" is the most meeting-app-shaped question; title search alone can't answer it.
- **Pros:** Turns ⌘K into the app's front door; infra (pgvector) already runs in docker-compose.
- **Cons:** Needs an indexing strategy for segments + chat messages; ranking/highlighting work.
- **Context:** Deferred from the 2026-07-13 glassy redesign design review (D8). Client-side title search (T4) ships first and defines the dropdown UI this plugs into.
- **Depends on:** T4 search UI from redesign-plan.md.
