# Implementation plan

Authoritative implementation strategy for tareq-skills (owner-approved 2026-10-29, D-18).
Milestone **status** is tracked in [`roadmap.md`](roadmap.md); decisions in
[`decisions.md`](decisions.md); data model and rules in
[`architecture/catalog.md`](architecture/catalog.md).

## Direction

Build the **smallest practical operational version first**, then validate it on the SMMS
project in real use before expanding. No advanced feature is built before the basic
workflow works in a real project.

## Essential capabilities (minimum operational version)

| # | Capability | Milestone |
|---|---|---|
| 1 | Central skill library and catalog | M1 (schema), M4 (content) |
| 2 | Project technology detection | M1 (definitions), M3 (evaluation) |
| 3 | Smallest suitable skill set per project and task | M3 |
| 4 | Detect duplicate, incompatible, conflicting skills | M1 (validation), M3 (reporting) |
| 5 | Link skills to projects | M1 (`.tareq/skills.yaml`), M3 |
| 6 | Version pinning and lockfiles | M1 (schema), M3 (generation) |
| 7 | Synchronization only after explicit owner approval | M3 |
| 8 | Claude Code and OpenCode support | M2 (requirements), M3 (adapters) |
| 9 | Add new skills, notes, lessons — classified and reviewed | M3 (intake), M4 |
| 10 | Identify projects that may benefit from a new skill and propose adoption | M6 |
| 11 | Roll back to a previous working configuration | M1 (lock design), M3 |
| 12 | Project-level skill history and categorized instructions | M3 (templates), M5 |
| 13 | Efficient context and token management | M1 (budget), M3, M5 (measured) |

## Deferred (not cancelled — revisit when real usage shows a need)

Visual dashboard · automatic updates across all projects · advanced AI recommendations ·
multi-user approval workflows · scheduled monitoring · skill marketplace · detailed
token-consumption analytics.

## Milestones

Each milestone starts only after the owner approves the previous one (merged PR).

| # | Scope | Depends on | Acceptance criteria |
|---|---|---|---|
| M0 | Repo bootstrap, rules, docs | — | Push verified; structure documented. |
| M1 | Catalog schemas, detection definitions, packs, overlays, conflict/compatibility validation, project config + lock schemas | M0 | Schemas + validator; positive and negative fixtures; every rule has a test that fails when the rule is broken. |
| M2 | Read official Claude Code and OpenCode docs; adapter requirements | M1; O-12 (OpenCode network access) | One requirements section per tool with verified paths, fields, discovery, permissions; O-05 and O-09 decided. |
| M3 | Minimum manager: `scan`, `select`, lock generation, approval-gated `sync`, `rollback`, intake of skills/notes/lessons, project history templates, both adapters | M2 | End-to-end on a synthetic project: detect → propose → approve → lock → generate → roll back; tests on real behavior. |
| M4 | Seed library: review and import only the skills SMMS needs (copy, `SOURCE.txt`, pinned SHA); default `core` pack contents | M3; owner approval per skill | Each import reviewed (security, license, overlap) and approved; catalog validates. |
| M5 | SMMS pilot (SMMS as client) | M4; owner approval to touch SMMS | SMMS runs from lock; enabled descriptions and context cost measured before/after; owner confirms the workflow is usable. |
| M6 | Expansion: remaining requested repos (O-07), cross-project adoption proposals, tooling (O-08) | M5 accepted | Driven by pilot findings; each addition approved. |
| M7 | CI and quality: tests on PRs, secret scanning, schema/link checks | M1 (can start any time after) | CI green on PRs. |

**Gate to expand (M6):** the M5 pilot shows the basic workflow works in real use, with
measured context savings and no unresolved defects.

## Working principles

- Prefer consolidated work packages over many tiny tasks.
- Avoid unnecessary model handoffs and parallel agents.
- No duplicate documentation: update the owning document; reference instead of copying.
- Do not repeat successful tests without a specific reason.
- Do not implement features outside the current milestone.
- Test actual behavior, not just configuration or documentation.
- Preserve security, compatibility, version control, and rollback.
