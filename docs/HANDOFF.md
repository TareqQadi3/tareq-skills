# HANDOFF — current state

Living summary for the next session. Update at the end of every milestone.
History and full rationale: [`TAREQ-SKILLS-PROJECT-HANDOFF.md`](TAREQ-SKILLS-PROJECT-HANDOFF.md)
(do not edit). Rules: [`../CLAUDE.md`](../CLAUDE.md). Strategy:
[`implementation-plan.md`](implementation-plan.md).

**Last updated:** 2026-10-30 · **Milestone:** M4 preparation done (proposal only; nothing imported) · **Next:** owner decides O-16…O-19, then one import PR; O-15 and O-10 before M5

## State

| Item | State |
|---|---|
| Repository | `TareqQadi3/tareq-skills`, private, default branch `main` |
| `main` | M3 merged via PR #4, merge commit `ef45bff` |
| M4 branch | `claude/m4-smms-prep` → PR to `main` (not merged): proposal + two manager fixes |
| Manager | `bin/tareq` (scan, select, sync, rollback, recover, doctor, add-skill, note); see `architecture/manager.md` |
| Approval | Enforced by the tool on the controlling terminal; fails closed elsewhere (exit 2). **Not available in the owner's iPhone + cloud environment**; see `architecture/approval.md` and O-15 |
| Integration | Requirements R-01…R-11 in `architecture/adapters.md`; OpenCode verified from docs source only |
| Catalog | Schemas in `catalog/schema/`; `skills.yaml` empty (no skills); `stacks.yaml` has 11 detection definitions; no packs/overlays yet |
| Validator | `python3 bin/validate_catalog.py [--catalog DIR] [--project-dir DIR]` |
| Tests | `python3 -m unittest discover -s tests -v` — 215 tests (1 opt-in live Claude Code test skipped by default); `python3 tests/mutation_check.py` — safeguard mutation check |
| Branch protection on `main` | **Not configured** (`protected: false`). Owner action required — see below. |
| Skills in library | None. The proposed 8 are described in [`m4-smms-proposal.md`](m4-smms-proposal.md); SMMS was inspected read-only and not changed. |
| OpenCode | Docs read from official GitHub source (D-19); not installed or run. `opencode.ai` blocked by network policy. |

## Owner actions pending

1. Review and merge the M4 PR (proposal and manager fixes only).
2. Answer O-16…O-19 in [`m4-smms-proposal.md`](m4-smms-proposal.md) §7.
3. Decide O-15 (approval channel) before M5; applying to SMMS needs a terminal the owner controls.
4. Protect `main` (GitHub → Settings → Rules → Rulesets → "Require a pull request before
   merging" + "Block force pushes"); on private repos this may need GitHub Pro.
5. SMMS (not touched here): a plaintext login credential is committed in
   `Desktop/SMMS-FINAL/.claude/settings.local.json` of a public repository; rotate it and remove the file.

## Next actions

- After the owner's reply: one PR importing the approved skills with provenance, the `core` and
  `smms-core` packs, and catalog the `tareq-skill` manager skill.
- Refresh the six SMMS project skills (O-18) as a separate work package.

## Do not

- Re-run the 111/13 skills audit or re-open approved architecture.
- Touch SMMS, Qeedha, Qeedha B, or any other project.
- Import, install, or run anything from external skill repositories before M4 approval.
