# Roadmap

Milestones are recommendations from the original handoff (§14). Each milestone starts
only after explicit owner approval of the previous one.

| # | Milestone | Scope | Acceptance criteria | Status |
|---|---|---|---|---|
| M0 | Verification and bootstrap | Verify write access; create `main`; repo structure; `README`, `CLAUDE.md`, `.gitignore`, docs (handoff, log, decisions, roadmap, architecture). | Successful push; structure documented; PR open for review. | In review |
| M1 | Catalog schema and rules | Schemas for `skills.yaml`, `stacks.yaml`, packs, overlays, `skills.lock`; document selection, conflict resolution, context budget. | Documented JSON Schema/YAML schema + examples; simple schema tests. | Not started |
| M2 | Official docs verification and adapter design | Finish Claude Code skills docs review; read OpenCode docs (needs network allowance). | Adapter requirements document per tool. | Not started |
| M3 | `tareq-skill` and tools | Manager skill (owner rules, selection, logging); `scan`, `select`, `sync`, `audit`, `doctor`, `rollback`; client templates. | Working tools with tests. | Not started |
| M4 | Reviewed initial import | Fetch and review the 8 requested repos one by one (security, license, overlap); import by copy with `SOURCE.txt` and pinned SHA. Then, separately approved, copy (not move) SMMS skills. | Owner-approved imports with full provenance. | Not started |
| M5 | Pilot client, then SMMS | SMMS manifest; measure context budget before/after; SMMS cleanup plan (separate owner decision). | Measured context reduction; client works from lock file. | Not started |
| M6 | Project tooling (MCP / browser / security) | Evaluate requested tools step by step; document what works in Claude Code and OpenCode. | Owner-selected tools documented. | Not started |
| M7 | CI and quality | Secret scanning, schema and link validation, automatic conflict report, rollback docs. | CI green on PRs. | Not started |
