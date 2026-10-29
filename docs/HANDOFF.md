# HANDOFF — current state

Living summary for the next session. Update at the end of every milestone.
History and full rationale: [`TAREQ-SKILLS-PROJECT-HANDOFF.md`](TAREQ-SKILLS-PROJECT-HANDOFF.md)
(do not edit). Rules: [`../CLAUDE.md`](../CLAUDE.md).

**Last updated:** 2026-10-29 · **Milestone:** M0 complete, in PR review · **Next:** M1 (needs owner approval)

## State

| Item | State |
|---|---|
| Repository | `TareqQadi3/tareq-skills`, private, default branch `main` |
| `main` | README-only initial commit `b507d80` |
| M0 branch | `claude/m0-bootstrap` → Pull Request to `main` (not merged) |
| Write access | PASS (initial push succeeded) |
| Branch protection on `main` | **Not configured.** This session has no tool to set it (GitHub MCP has no branch-protection API; no `gh` access). Owner action required — see below. |
| Skills in library | None. Nothing imported, installed, or changed. |
| OpenCode docs | Unverified; domain not allowed in session network policy (O-12). |

## Owner actions pending

1. Review and merge the M0 Pull Request.
2. Protect `main` (GitHub → Settings → Rules → Rulesets → New branch ruleset → target
   `main` → "Require a pull request before merging" + "Block force pushes").
   Note: rulesets/branch protection on **private** repos may require GitHub Pro; on the
   free plan the option may be unavailable — then D-11 is enforced by convention via
   `CLAUDE.md`.
3. Approve M1 when ready.

## Next actions (M1, after approval)

- Define schemas for `catalog/skills.yaml`, `catalog/stacks.yaml`, packs, overlays, and
  `.tareq/skills.lock`, with examples and lightweight schema tests.
- Resolve open decisions needed by M1: O-01, O-02, O-03, O-04, O-11
  ([`decisions.md`](decisions.md)).

## Do not

- Re-run the 111/13 skills audit or re-open approved architecture.
- Touch SMMS, Qeedha, Qeedha B, or any other project.
- Import, install, or run anything from external skill repositories before M4 approval.
