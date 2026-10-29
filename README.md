# tareq-skills

Centralized, reusable skills library for all of Tareq's current and future projects,
with a reusable manager skill (`tareq-skill`) that selects and activates the best
compatible skills per project, for **Claude Code** and **OpenCode**.

> Status: **M0 — bootstrap**. Structure and documentation only. No skills have been
> imported yet. See [`docs/HANDOFF.md`](docs/HANDOFF.md) for the current state.

## Why

- Every enabled skill's description is loaded into context on every turn (truncated at
  1,536 chars). Too many skills burn tokens and drown out the important ones.
- Overlapping skills conflict on the same requests.
- User-level skills in cloud sessions are ephemeral and disappear with the session.

This repository is the single, versioned source of truth that fixes those problems.

## Principles

1. **Single source of truth.** One catalog describes every skill: category, source,
   version, license, status, conflicts, and context cost.
2. **Independence.** This repo is fully independent of any project (SMMS included).
   Projects are *clients* that consume the library through their own manifest.
3. **Context budget.** Only a bounded set of skill descriptions is active per project;
   the rest stays available on demand.
4. **Provenance and pinning.** Every imported skill records its origin URL, commit SHA,
   license, fetch date, and content hash. Clients pin versions in a lock file.
5. **Never delete.** Disabled skills stay in the library with status `disabled`.
6. **Review before activation.** No external script runs on import; nothing is activated
   in a project without explicit owner approval.
7. **Generated adapters.** Tool-specific output (Claude Code, OpenCode) is generated from
   one manifest and never edited by hand.

## Repository map

| Path | Purpose | Milestone |
|---|---|---|
| `library/<category>/<skill>/` | Verbatim skill copies + `SOURCE.txt` | M4 |
| `catalog/` | `skills.yaml`, `stacks.yaml`, `packs/`, `overlays/` | M1 |
| `tareq-skill/` | The manager skill (`SKILL.md` + scripts) | M3 |
| `bin/` | Tools: `scan`, `select`, `sync`, `audit`, `doctor`, `rollback` | M3 |
| `templates/` | Client project templates (skills manifest, project log, instructions) | M3 |
| `docs/` | Handoff, project log, decisions, roadmap, architecture | M0 |
| `CLAUDE.md` | Permanent working rules for AI agents in this repo | M0 |

Client projects will hold `.tareq/skills.yaml` (selected packs/skills) and
`.tareq/skills.lock` (resolved, pinned list). Format is defined in M1.

## Documentation

- [`docs/HANDOFF.md`](docs/HANDOFF.md) — current state and next actions (start here)
- [`docs/decisions.md`](docs/decisions.md) — approved and open decisions
- [`docs/roadmap.md`](docs/roadmap.md) — milestones M0–M7 and acceptance criteria
- [`docs/project-log.md`](docs/project-log.md) — milestone log
- [`docs/architecture/overview.md`](docs/architecture/overview.md) — approved architecture
- [`docs/TAREQ-SKILLS-PROJECT-HANDOFF.md`](docs/TAREQ-SKILLS-PROJECT-HANDOFF.md) — original handoff (Arabic, authoritative history; do not edit)

## License

Private repository. No license is granted at this time.
