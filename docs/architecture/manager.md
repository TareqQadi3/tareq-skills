# Manager (M3): `bin/tareq`

Minimum operational manager (D-18). Code: `bin/tareq` → `bin/tareqlib/`. Python 3 + PyYAML +
jsonschema only (D-17). Operator guide for agents: [`tareq-skill/SKILL.md`](../../tareq-skill/SKILL.md).
Integration rules: [`adapters.md`](adapters.md). Catalog rules: [`catalog.md`](catalog.md).

## Commands

| Command | Does | Writes |
|---|---|---|
| `scan --project P` | Evaluates `catalog/stacks.yaml` rules (file, content regex, npm/maven/gradle/pip dependency, `implies`). Never follows symlinks; skips `.git`, `node_modules`, build dirs. | nothing |
| `select --project P [--tags a,b] [--init …]` | Proposes default packs + packs triggered by detected stacks; drops inactive skills; lists same-priority conflicts for the owner. | `.tareq/skills.yaml` only with `--init`, and only if absent |
| `sync --project P [--ref R \| --commit C]` | Dry-run plan + summary + fingerprint. | nothing |
| `sync … --apply F --commit C` | Recomputes the plan and applies it only if its fingerprint is `F`. | generated files, owned settings keys, lock, history |
| `rollback --project P --to REV [--apply F]` | Regenerates the exact state recorded by the lock at client revision `REV`. | same as sync; never `.tareq/skills.yaml` |
| `doctor --project P [--library S]` | Read-only: lock validity, hand-edited or missing generated files, stale config, personal-skill collisions, manual skills, OpenCode status, and (with `--library`) full lock-vs-catalog check. | nothing |
| `add-skill DIR --id … --category … --version … [--authored \| --url --commit --license]` | Copies a skill verbatim into `library/` with `SOURCE.txt` and adds a `candidate` / review-pending entry. Atomic; never executes content. | `library/`, `catalog/skills.yaml` |
| `note --project P --category C TEXT` | Appends a categorized note or lesson to `.tareq/history.md`. | `.tareq/history.md` |

Library source defaults to `catalog.repo` in the project config. The library is cloned into
`$TAREQ_CACHE` (default `~/.cache/tareq-skills`), outside the client repo, and checked out
detached at the exact commit. Every use verifies `HEAD` and a clean tree (D-21, R-14).

## Client project layout after sync

| Path | Owner | Notes |
|---|---|---|
| `.tareq/skills.yaml` | owner | Never written by sync or rollback |
| `.tareq/skills.lock` | tareq | Version 2: adds `generated` (path + hash of every generated file), `settings` (owned keys and list items per file, `created`), `skills[].output_hash`, `plan_fingerprint`, optional `rollback` |
| `.tareq/history.md` | append-only | Sync/rollback entries; owner notes and lessons |
| `.tareq/SKILLS-<category>.md` | tareq | Skill register with source links (read on demand) |
| `.claude/rules/tareq-skills.md` | tareq | Short, always-loaded pointer (Claude; OpenCode via `instructions`) |
| `.claude/skills/<id>/` | tareq | Verbatim copies (frontmatter rewritten only for overlays, recorded by `output_hash`) |
| `.claude/settings.json` → `skillOverrides.<id>` | tareq key | Manual skills (`user-invocable-only`); other keys untouched |
| `opencode.json` → `permission.skill.<id>`, `instructions[]` | tareq keys | OpenCode: documented only, NOT TESTED |
| anything else | owner | Never read for writing, never removed |

## Safeguards: implementation and tests

| ID | Implementation (`bin/tareqlib/sync.py` unless noted) | Failing-path tests (`tests/test_manager.py`) |
|---|---|---|
| R-12 | Writes allowed only to absent paths or owned paths whose current hash equals the lock. Unowned files, unowned keys, unmanaged files inside a skill dir, and invalid JSON all block. Overwriting an unmanaged skill needs `--approve-overwrite <id>`; taking one over needs `--adopt <id>` with identical bytes. Writes never go through symlinks. | `test_r12_*`, `test_safe_dest_rejects_symlink_escape` |
| R-13 | Before every plan: same id in `~/.claude/skills`, `~/.config/opencode/skills`, `~/.agents/skills`, project `.opencode/skills` / `.agents/skills`, or a manual skill declaring that name → blocked. Apply re-plans, so a collision that appears after planning also blocks. | `TestCollisions` |
| R-14 | Full 40-char commit only; checkout `HEAD` and clean tree verified. The library catalog is fully validated, including every content hash. Per-skill source hash is checked before copying. After writing, every desired file, each skill directory, and the lock are verified. | `TestHashesAndPinning`, `test_checkout_requires_full_commit` |
| R-15 | `sync` without `--apply` is a dry run that prints the summary and fingerprint. Blocked plans cannot be applied. | `test_r15_*`, `test_cli_plan_apply_roundtrip` |
| R-16 | Disabled/candidate skills cannot be synced and stay in the catalog. Removal touches only owned, unmodified files. | `test_r16_*` |
| R-17 | Summary and doctor mark OpenCode output "documented only; NOT TESTED". | `TestReportingAndDoctor` |
| R-18 | Rollback uses the same ownership rules. A hand-edited owned file is left and reported, the config is never written, and generated state must reproduce the target lock's hashes exactly. | `TestRollback` |
| R-19 | Snapshot of every touched path into a private transaction dir. Temp-file + `os.replace` writes. On any exception (including verification), bytes and presence are restored, created dirs and temp files removed, and the restored state re-verified. | `TestAtomicity` (failure injected at every step), `test_rollback_is_atomic` |
| R-20 | Fingerprint = canonical hash of library source + commit, config hash, source hashes, current state of every touched path, ordered operations, and lock content. Apply recomputes from scratch and refuses any difference. | `TestApprovalFingerprint` |

Mutation check: disabling each safeguard in a scratch copy made its tests fail (see project log).

## Live Claude Code check

`TAREQ_LIVE_CLAUDE=1 python3 -m unittest discover -s tests -p test_live_claude.py` syncs a
temp project and asks a real `claude -p` session which skills and rules it sees. It is
opt-in because it calls the model. OpenCode is not installed, so its output is documented only.

## Limitations

- Settings files are rewritten as formatted JSON (2-space indent). Content outside owned
  keys is preserved, but the original formatting is not. JSONC (`opencode.json` with
  comments) is refused, not edited.
- Rollback needs the client project to be a git repository holding the earlier lock.
- `select` is rule-based (stacks, packs, tags). Task-aware AI recommendation is deferred.
- The manager skill (`tareq-skill/`) is not yet a catalog entry, so it is not distributed
  by sync. Cataloging it is part of seeding (M4).
- Concurrent runs on the same project are not locked against each other. Each apply
  re-verifies the fingerprint, so a concurrent change makes the later apply refuse
  rather than corrupt.
