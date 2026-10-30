# HANDOFF — current state

Living summary for the next session. Update at the end of every milestone.
History and full rationale: [`TAREQ-SKILLS-PROJECT-HANDOFF.md`](TAREQ-SKILLS-PROJECT-HANDOFF.md)
(do not edit). Rules: [`../CLAUDE.md`](../CLAUDE.md). Strategy:
[`implementation-plan.md`](implementation-plan.md).

**Last updated:** 2026-10-29 · **Milestone:** M3 complete (review fixes F1–F6 applied), in PR review · **Next:** M4 (needs owner approval); O-15 before M5

## State

| Item | State |
|---|---|
| Repository | `TareqQadi3/tareq-skills`, private, default branch `main` |
| `main` | M2 merged via PR #3, merge commit `c09924b` |
| M3 branch | `claude/m3-manager` → PR to `main` (not merged) |
| Manager | `bin/tareq` (scan, select, sync, rollback, recover, doctor, add-skill, note); see `architecture/manager.md` |
| Approval | Enforced by the tool on the controlling terminal; fails closed elsewhere (exit 2). **Not available in the owner's iPhone + cloud environment**; see `architecture/approval.md` and O-15 |
| Integration | Requirements R-01…R-11 in `architecture/adapters.md`; OpenCode verified from docs source only |
| Catalog | Schemas in `catalog/schema/`; `skills.yaml` empty (no skills); `stacks.yaml` has 11 detection definitions; no packs/overlays yet |
| Validator | `python3 bin/validate_catalog.py [--catalog DIR] [--project-dir DIR]` |
| Tests | `python3 -m unittest discover -s tests -v` — 215 tests (1 opt-in live Claude Code test skipped by default); `python3 tests/mutation_check.py` — safeguard mutation check |
| Branch protection on `main` | **Not configured** (`protected: false`). Owner action required — see below. |
| Skills in library | None. Nothing imported, installed, or changed. |
| OpenCode | Docs read from official GitHub source (D-19); not installed or run. `opencode.ai` blocked by network policy. |

## Owner actions pending

1. Review and merge the M3 PR.
2. Decide O-15: how the owner approves a sync from the iPhone/cloud environment (today only a terminal the owner controls can).
3. Approve M4 scope: which SMMS skills to seed, and cataloging the manager skill.
3. Protect `main` (GitHub → Settings → Rules → Rulesets → New branch ruleset → target
   `main` → "Require a pull request before merging" + "Block force pushes"). On private
   repos this may require GitHub Pro; otherwise D-11 is enforced by convention.

## Next actions (M4, after approval)

- Seed the library with only the skills SMMS needs (D-18), reviewed one by one; catalog
  `tareq-skill`; define the default `core` pack.

## Do not

- Re-run the 111/13 skills audit or re-open approved architecture.
- Touch SMMS, Qeedha, Qeedha B, or any other project.
- Import, install, or run anything from external skill repositories before M4 approval.
