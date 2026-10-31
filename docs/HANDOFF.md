# HANDOFF — current state

Living summary for the next session. Update at the end of every milestone.
History and full rationale: [`TAREQ-SKILLS-PROJECT-HANDOFF.md`](TAREQ-SKILLS-PROJECT-HANDOFF.md)
(do not edit). Rules: [`../CLAUDE.md`](../CLAUDE.md). Strategy:
[`implementation-plan.md`](implementation-plan.md).

**Last updated:** 2026-10-31 · **Milestone:** M4 complete, in PR review (8 skills imported; nothing applied to SMMS) · **Next:** owner reviews the 6 SMMS skills; O-15 before M5

## State

| Item | State |
|---|---|
| Repository | `TareqQadi3/tareq-skills`, private, default branch `main` |
| `main` | M3 merged via PR #4, merge commit `ef45bff` |
| M4 branch | `claude/m4-smms-prep` → PR #5 to `main` (not merged): import, refresh, two manager fixes |
| Manager | `bin/tareq` (scan, select, sync, rollback, recover, doctor, add-skill, note); see `architecture/manager.md` |
| Approval | Enforced by the tool on the controlling terminal; fails closed elsewhere (exit 2). **Not available in the owner's iPhone + cloud environment**; see `architecture/approval.md` and O-15 |
| Integration | Requirements R-01…R-11 in `architecture/adapters.md`; OpenCode verified from docs source only |
| Catalog | 8 skills; packs `core` (default) and `smms-core`; `stacks.yaml` has 11 detection definitions; no overlays |
| Validator | `python3 bin/validate_catalog.py [--catalog DIR] [--project-dir DIR]` |
| Tests | `python3 -m unittest discover -s tests -v` — 218 tests (1 opt-in live Claude Code test skipped by default); `python3 tests/mutation_check.py` — 49 safeguard mutations |
| Branch protection on `main` | **Not configured** (`protected: false`). Owner action required — see below. |
| Skills in library | Active: `systematic-debugging`, `test-driven-development` (MIT, pinned). Candidate (review pending): the six `smms-*` skills, v1.1.0. SMMS was inspected read-only and not changed; see [`m4-smms-proposal.md`](m4-smms-proposal.md) |
| OpenCode | Docs read from official GitHub source (D-19); not installed or run. `opencode.ai` blocked by network policy. |

## Owner actions pending

1. Review and merge the M4 PR (#5).
2. Review the six SMMS skills (`library/*/smms-*`); approve each one that is correct so it can be made `active`.
3. Decide O-15 (approval channel) before M5; applying to SMMS needs a terminal the owner controls (D-26).
4. Protect `main` (GitHub → Settings → Rules → Rulesets → "Require a pull request before
   merging" + "Block force pushes"); on private repos this may need GitHub Pro.
5. SMMS (not touched here): a plaintext login credential is committed in
   `Desktop/SMMS-FINAL/.claude/settings.local.json` of a public repository; rotate it and remove the file.

## Next actions

- Small PR activating the approved SMMS skills; then the first SMMS trial (steps in `m4-smms-proposal.md` §8).
- Cataloging `tareq-skill` is deferred (not in the approved M4 set).

## Do not

- Re-run the 111/13 skills audit or re-open approved architecture.
- Touch SMMS, Qeedha, Qeedha B, or any other project.
- Import, install, or run anything from external skill repositories before M4 approval.
