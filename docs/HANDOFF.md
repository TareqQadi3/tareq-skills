# HANDOFF — current state

Living summary for the next session. Update at the end of every milestone.
History and full rationale: [`TAREQ-SKILLS-PROJECT-HANDOFF.md`](TAREQ-SKILLS-PROJECT-HANDOFF.md)
(do not edit). Rules: [`../CLAUDE.md`](../CLAUDE.md).

**Last updated:** 2026-10-29 · **Milestone:** M0 merged · **Next:** M1 plan awaiting owner decisions

## State

| Item | State |
|---|---|
| Repository | `TareqQadi3/tareq-skills`, private, default branch `main` |
| `main` | M0 merged via PR #1, merge commit `5e3366a` |
| Working branch | `claude/m1-catalog` (M1; no PR yet) |
| Write access | PASS (initial push succeeded) |
| Branch protection on `main` | **Not configured** (`protected: false`, GitHub API, 2026-10-29). This session cannot set it. Owner action required — see below. |
| Skills in library | None. Nothing imported, installed, or changed. |
| OpenCode docs | Unverified; domain not allowed in session network policy (O-12). |

## Owner actions pending

1. Protect `main` (GitHub → Settings → Rules → Rulesets → New branch ruleset → target
   `main` → "Require a pull request before merging" + "Block force pushes").
   Note: rulesets/branch protection on **private** repos may require GitHub Pro; on the
   free plan the option may be unavailable — then D-11 is enforced by convention via
   `CLAUDE.md`.
2. Answer the M1 open decisions (O-02, O-03, O-04, O-13) and approve M1.

## Next actions (M1, after approval)

- Define schemas for `catalog/skills.yaml`, `catalog/stacks.yaml`, packs, overlays, and
  `.tareq/skills.lock`, with examples and lightweight schema tests.
- Open decisions needed by M1: O-02, O-03, O-04, O-13 ([`decisions.md`](decisions.md)).
  O-01 and O-11 are resolved by keeping the approved names (D-13).

## Do not

- Re-run the 111/13 skills audit or re-open approved architecture.
- Touch SMMS, Qeedha, Qeedha B, or any other project.
- Import, install, or run anything from external skill repositories before M4 approval.
