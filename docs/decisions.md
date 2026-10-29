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

## Open

| ID | Question | Current recommendation | Needed by |
|---|---|---|---|
| O-02 | Context budget cap and default packs (`core` contents). | ≈ 40 active descriptions (estimate). | M1 |
| O-03 | License policy: which licenses are accepted; handling of unlicensed skills. | Record every license; isolate non-redistributable ones. | M1 |
| O-04 | Conflict resolution order. | project-specific → stack-specific → general → newest → clearest license. | M1 |
| O-05 | Claude Code distribution: pinned copies in `.claude/skills/`, private plugin marketplace, or both. | Decide after M2 doc review. | M2 |
| O-06 | `disable-model-invocation: true` for `arena` and similar costly skills. | Yes (manual-only). | M4 |
| O-07 | Fate of the 8 requested external repos (emilkowalski, impeccable, taste-skill, roast-room, marketingskills, instagram, youtube, arena-skill-16) and figma / playwright MCP. | Review one by one before any import. | M4 |
| O-08 | Browser, testing, and security tooling choices. | Evaluate step by step. | M6 |
| O-09 | How clients consume the library (clone, submodule, subtree, sync script, plugin). | Decide after M2. | M2–M3 |
| O-10 | SMMS skills cleanup (what to disable/merge). | Separate SMMS-track decision after M5. | M5 |
| O-12 | Allow the OpenCode docs domain in the session network policy. | Required to verify the OpenCode adapter. | M2 |
| O-13 | Language for validation and manager tooling (M1 tests, M3 `bin/`). | Python 3 + PyYAML + jsonschema. | M1 |
