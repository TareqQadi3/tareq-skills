# Decisions

Source of truth for owner decisions. Section references (§) point to
[`TAREQ-SKILLS-PROJECT-HANDOFF.md`](TAREQ-SKILLS-PROJECT-HANDOFF.md).

## Approved

| ID | Decision | Date | Ref |
|---|---|---|---|
| D-01 | `tareq-skills` is a fully independent, private GitHub repository. No temporary library inside SMMS; no skills copied into SMMS. | 2026-10-29 | §2, §8.2 |
| D-02 | Keep: central catalog, `tareq-skill` manager, per-project manifest, Claude Code and OpenCode adapters, version pinning, rollback. | 2026-10-29 | §8.2 |
| D-03 | `tareq-skill` is generic, not tied to SMMS. Projects are clients. | 2026-10-29 | §2 |
| D-04 | No install/move/disable/delete/modify of any existing skill (SMMS 111, user-level 13) until explicitly approved. | 2026-10-29 | §12 |
| D-05 | The SMMS skills cleanup (~70 to disable) is **not** approved; it is deferred until the library is ready. | 2026-10-29 | §8.5 |
| D-06 | SMMS feature work and skills work run in parallel, in separate conversations. | 2026-10-29 | §8.1, §8.4 |
| D-07 | Owner's permanent rules (models, agents, reports, no redundant work, safety, logs, skill selection, step-by-step dialog). | 2026-10-29 | §5 |
| D-08 | Repository layout: `library/`, `catalog/`, `tareq-skill/`, `bin/`, `templates/`, plus `docs/` and `docs/architecture/`. | 2026-10-29 | §3, M0 approval |
| D-09 | `main` established with a README-only initial commit; all later changes go through `claude/*` branches and Pull Requests. | 2026-10-29 | M0 approval |
| D-10 | Repository stays private; no `LICENSE` file for now. | 2026-10-29 | M0 approval |
| D-11 | Require Pull Requests for changes to `main` (branch protection, if GitHub permits). | 2026-10-29 | M0 approval |
| D-12 | The original handoff is preserved verbatim as `docs/TAREQ-SKILLS-PROJECT-HANDOFF.md`; `docs/HANDOFF.md` is its concise, living counterpart. | 2026-10-29 | M0 approval |
| D-13 | Keep the approved names (`tareq-skills`, `tareq-skill`, §3 layout); library-level skill status values are `candidate`, `active`, `disabled` (§3). Resolves O-01, O-11. | 2026-10-29 | §3, M1 planning |
| D-14 | Description budget (O-02): 40 enabled auto-invoked descriptions is a configurable **hard maximum, not a target**; always select the smallest suitable set. Default pack contents are chosen at M4. | 2026-10-29 | M1 approval |
| D-15 | License policy (O-03): accept MIT, Apache-2.0, BSD (2/3-Clause, 0BSD), ISC. Missing or other licenses stay `candidate` and need an explicit owner exception to activate; missing license ≠ permission. | 2026-10-29 | M1 approval |
| D-16 | Conflict priority (O-04): project → technology (stack) → general. Same-level conflicts go to the owner; never decided by recency, popularity, or license clarity. "Latest" applies only to versions of the same skill. | 2026-10-29 | M1 approval |
| D-17 | Implementation language (O-13): Python 3 + PyYAML + jsonschema; no other language without a concrete reason and approval. | 2026-10-29 | M1 approval |
| D-18 | Strategy: smallest operational version first, validated on SMMS before expansion; see `implementation-plan.md` (capabilities, deferred features, milestones). | 2026-10-29 | M1 approval |
| D-19 | O-12 closed without a network change: OpenCode docs are read from the official docs source in `github.com/sst/opencode` (commit recorded in `architecture/adapters.md`); `opencode.ai` stays blocked. | 2026-10-30 | M2 |
| D-20 | Distribution (O-05): pinned verbatim copies committed in the client's `.claude/skills/` only (shared with OpenCode); no plugin marketplace. | 2026-10-30 | M2 approval |
| D-21 | Consumption (O-09): a sync command fetches the library at an exact commit outside the client repo and writes generated files + lock into it; no submodule/subtree. | 2026-10-30 | M2 approval |
| D-22 | Sync safeguards: never overwrite/delete existing project skills without explicit approval; detect name collisions before sync; pin every sync to an exact commit and verify content hashes; show a change summary and get approval before applying; preserve disabled skills and manually maintained project files; report documented OpenCode compatibility separately from tested behavior (untested is never PASS). See R-12…R-17 in `architecture/adapters.md`. | 2026-10-30 | M2 approval |

## Open

| ID | Question | Current recommendation | Needed by |
|---|---|---|---|
| O-06 | `disable-model-invocation: true` for `arena` and similar costly skills. | Yes (manual-only). | M6 |
| O-07 | Fate of the 8 requested external repos (emilkowalski, impeccable, taste-skill, roast-room, marketingskills, instagram, youtube, arena-skill-16) and figma / playwright MCP. | Review one by one before any import; deferred until after the SMMS pilot (D-18). | M6 |
| O-08 | Browser, testing, and security tooling choices. | Evaluate step by step. | M6 |
| O-10 | SMMS skills cleanup (what to disable/merge). | Separate SMMS-track decision after M5. | M5 |
| O-14 | License for owner-authored local skills (e.g. `tareq-skill`) with no license file: exempt `source.type: local` from D-15, or require a recorded `license_exception` each time. | Exempt local skills authored in this repo. | M3 |
