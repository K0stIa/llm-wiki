# Session Memory

User preferences, collaboration model, active project context. Loaded at session start (cold start) and on-demand.

## Tiers (MEMORY.md T1/T2/T3 system)

- **T1 (Hot):** Loaded at every session start. User identity, collaboration model, active project context.
- **T2 (Warm):** Loaded on-demand via grep or explicit load.
- **T3 (Cold):** Historical record. Grep-findable but not loaded automatically.

## References

- [wiki_memory/session.md](/wiki_memory/session.md) — Current session context
