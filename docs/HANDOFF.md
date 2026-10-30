# HANDOFF — current state

Living summary for the next session. Update at the end of every milestone.
History and full rationale: [`TAREQ-SKILLS-PROJECT-HANDOFF.md`](TAREQ-SKILLS-PROJECT-HANDOFF.md)
(do not edit). Rules: [`../CLAUDE.md`](../CLAUDE.md). Strategy:
[`implementation-plan.md`](implementation-plan.md).

**Last updated:** 2026-10-29 · **Milestone:** M1 complete, in PR review · **Next:** M2 (needs owner approval)

## State

| Item | State |
|---|---|
| Repository | `TareqQadi3/tareq-skills`, private, default branch `main` |
| `main` | M0 merged via PR #1, merge commit `5e3366a` |
| M1 branch | `claude/m1-catalog` → PR to `main` (not merged) |
| Catalog | Schemas in `catalog/schema/`; `skills.yaml` empty (no skills); `stacks.yaml` has 11 detection definitions; no packs/overlays yet |
| Validator | `python3 bin/validate_catalog.py [--catalog DIR] [--project-dir DIR]` |
| Tests | `python3 -m unittest discover -s tests -v` — 88 tests, synthetic fixtures only (incl. `tests/fixtures/library/`) |
| Branch protection on `main` | **Not configured** (`protected: false`). Owner action required — see below. |
| Skills in library | None. Nothing imported, installed, or changed. |
| OpenCode docs | Unverified; domain not allowed in session network policy (O-12). |

## Owner actions pending

1. Review and merge the M1 PR.
2. Protect `main` (GitHub → Settings → Rules → Rulesets → New branch ruleset → target
   `main` → "Require a pull request before merging" + "Block force pushes"). On private
   repos this may require GitHub Pro; otherwise D-11 is enforced by convention.
3. Before M2: allow the OpenCode docs domain in the session network policy (O-12).

## Next actions (M2, after approval)

- Read official Claude Code skills docs (remaining part, §10-A) and OpenCode docs; write
  adapter requirements; decide O-05 and O-09. See `implementation-plan.md`.

## Do not

- Re-run the 111/13 skills audit or re-open approved architecture.
- Touch SMMS, Qeedha, Qeedha B, or any other project.
- Import, install, or run anything from external skill repositories before M4 approval.
