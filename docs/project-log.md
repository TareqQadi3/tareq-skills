# Project log

Meaningful milestones and results only. Newest last.

## 2026-10-29 — Pre-repo planning (SMMS conversation)

- Audited 111 SMMS repo-level skills and 13 user-level entries (read-only). Findings and
  conflict groups G1–G11: original handoff §6–§7.
- Owner approved an independent central library (`TareqQadi3/tareq-skills`, private).
- No existing skill was changed.

## 2026-10-29 — M0: verification and bootstrap

- Repository identity, read access, and push permission verified (GitHub API:
  `push: true`, `admin: true`; repo was empty).
- `main` created with a README-only initial commit `b507d80`; remote `HEAD` → `main`.
  Write access: **PASS**.
- Branch `claude/m0-bootstrap`: repo structure, `README.md`, `CLAUDE.md`, `.gitignore`,
  `docs/` (HANDOFF, decisions, roadmap, project log, architecture overview), original
  handoff archived verbatim (SHA-256 `20b62e6f…0188`).
- Branch protection on `main`: see `docs/HANDOFF.md` (not configurable from this session).
- Session model: `claude-opus-5-5` (from session metadata). No subagents used.

## 2026-10-29 — M0 merged

- PR #1 merged to `main` (merge commit `5e3366a`); content identical to PR head `d4f35ca`.
- `main` branch protection: not configured (`protected: false`); owner action pending.

## 2026-10-29 — M1: catalog schema and validation

- Decisions recorded: D-14 budget (hard max 40, not a target), D-15 licenses, D-16 conflict
  priority, D-17 Python, D-18 strategy (`implementation-plan.md`).
- Delivered: 7 JSON Schemas (`catalog/schema/`), `catalog/skills.yaml` (empty),
  `catalog/stacks.yaml` (11 stacks), `bin/validate_catalog.py`, `tests/` (61 tests, synthetic
  fixtures), `docs/architecture/catalog.md`, `docs/implementation-plan.md`; `roadmap.md`
  reduced to a status tracker.
- Tests: 61/61 PASS. Mutation check (license rule and pack-cycle rule disabled) made the
  matching tests fail, confirming they test real behavior.
- No skills imported; no existing skill or project touched.

## 2026-10-30 — M1 pre-merge review

- Fixed: priority resolution depended on id spelling in conflict chains (now visited by
  priority, then id); lock was not checked against the configuration (`lock-drift`) or for
  version/license/source/budget/used-pack consistency; library content hashes were never
  computed (`content-hash-mismatch`, `missing-content`, symlinks rejected); duplicate skill
  names; unsafe detection/overlay globs.
- Tests: 88/88 PASS. Mutation checks: old resolution algorithm, disabled content-hash,
  lock-drift, and path checks each make their matching tests fail.
- O-06 and O-07 moved to M6 per D-18; candidate repos and tools remain listed in O-07.

## 2026-10-30 — M2: agent integration requirements

- M1 merged (PR #2, `5056697`).
- Read official Claude Code docs (skills, memory, hooks, settings, plugins, marketplaces) and
  the OpenCode docs source (`sst/opencode@237a847`; `opencode.ai` blocked by network policy).
- Delivered `docs/architecture/adapters.md`: verified behavior, a common model (one shared
  `.claude/skills/` copy for both agents, settings-based invocation control, a
  `.claude/rules/` instructions file), requirements R-01…R-11, limitations.
- Live probes with Claude Code 2.1.312 confirmed copy, symlink, `disable-model-invocation`,
  `skillOverrides`, and CLAUDE.md/AGENTS.md/rules loading. OpenCode: NOT TESTED.
- Recommendations for O-05 and O-09 recorded; awaiting owner decision.
- Owner approved O-05 and O-09 (D-20, D-21) with sync safeguards (D-22 → R-12…R-17).
  M3 plan added to `implementation-plan.md`; M3 not started.
- O-14 approved (D-23: authored skills exempt from external license rule; third-party not).
  Added safeguards R-18…R-20 (D-24: owned-only rollback, atomic sync, plan-fingerprint
  approval). M3 authorized after PR #3 merge (D-25).

## 2026-10-30 — M3: minimum manager

- M2 merged (PR #3, `c09924b`); D-20…D-25 verified on `main`.
- Delivered `bin/tareq` + `bin/tareqlib/` (scan, select, sync plan/apply, rollback, doctor,
  add-skill, note); lock version 2; templates; `tareq-skill/SKILL.md`;
  `docs/architecture/manager.md`. Validator: R-03 name check, frontmatter check, D-23
  exemption for authored skills, rollback-aware lock checks.
- Tests: 158 run, 157 PASS + 1 opt-in live test skipped by default; live Claude Code test
  run separately: PASS (3 auto skills listed, manual skill hidden via `skillOverrides`,
  rules file loaded). OpenCode: documented only, NOT TESTED.
- Mutation checks: disabling R-12, R-13, R-14, R-15, R-18, R-19, R-20, R-05, and the
  owned-path and intake-path checks each made the matching tests fail.
- Defects found and fixed during M3: post-write verification covered only written files
  (now the whole desired state); failed intake left an empty category dir; a crafted lock
  could claim owner files; intake category/id path traversal.

## 2026-10-30 — M3 security review fixes (PR #4)

Independent review of PR #4 found six defects; owner approved fixes F1–F6 with tool-enforced
approval (Option A, D-26, D-27).

- Confirmed before fixing: lost update under concurrent runs; SIGKILL left a half-applied
  project with no recovery; hidden `--home` bypassed the collision check; a forged lock could
  delete user settings and a manual skill; `note`/`select --init` wrote through symlinks;
  a fingerprint was copyable (not proof of approval).
- Fixed: approval enforced by the tool on the controlling terminal and fail-closed elsewhere
  (`approval.py`); per-project `flock` (F1); durable journal + recovery + `recover` command
  (F2); `--home` removed, home from passwd, environment in the fingerprint, option
  abbreviations off (F3); ownership allowlist with library corroboration, settings-file
  deletion only if untouched, rollback trusts only the configured library (F4); symlink,
  directory and FIFO refusal in `note`/`select --init` (F5); R-19 wording corrected (F6).
- Found by the new tests and fixed: argparse prefix `--approve` matched `--approve-overwrite`;
  prompt summary could carry terminal escape sequences; a terminal I/O error would have crashed
  instead of denying; `recover` created `.tareq/` in a non-project directory.
- Found by mutation checks and closed with new tests: journal path allowlist and the
  destination component of the fingerprint were not independently tested.
- Mutation check (`python3 tests/mutation_check.py`): 47/47 safeguard mutations detected on the final code.
- Tests: 215 run (1 opt-in live test skipped by default). Live Claude Code check on the final
  output: PASS. SIGKILL at all 48 transaction steps and at all 11 recovery steps: PASS.
  Power-loss durability and a real person typing on a real device: NOT TESTED. OpenCode: NOT TESTED.
- In this cloud session the real CLI refuses `--apply` (exit 2): the owner's iPhone + cloud
  environment cannot approve a sync. Decision O-15.

## 2026-10-30 — M4: SMMS seed proposal (preparation only)

- M3 merged (PR #4, `ef45bff`). SMMS inspected read-only at `claude/feature-program-1`
  (`a21bfb8`); `main` is stale and has no skills.
- Findings: the six SMMS project skills are stale (Flyway, inventory, notifications); all 86
  skills with `SOURCE.txt` are byte-identical to `spruvex-r@86b8eac`, which ships no license files;
  exact MIT upstream commits found for `systematic-debugging` and `test-driven-development`.
  A plaintext credential is committed in SMMS (reported, not touched).
- Proposed 8 of 111 skills (2,014 description characters; budget 8/40). Detail:
  `m4-smms-proposal.md`.
- Manager fixes: `scan` no longer reads skill directories as project files (was reporting
  Python/Node); `add-skill --authored` can record the origin it was derived from. Tests and
  mutation entries added.
- Scratch dry run: validator 0 errors, `select` proposes `core`, `sync` plan ready with
  `--adopt`/`--approve-overwrite`. Apply NOT attempted (needs a terminal, D-26).
- Nothing imported into the library; SMMS unchanged.
