# Manager (M3): `bin/tareq`

Minimum operational manager (D-18). Code: `bin/tareq` → `bin/tareqlib/`. Python 3 + PyYAML +
jsonschema only (D-17). Operator guide for agents: [`tareq-skill/SKILL.md`](../../tareq-skill/SKILL.md).
Integration rules: [`adapters.md`](adapters.md). Catalog rules: [`catalog.md`](catalog.md).
Approval design and supported environments: [`approval.md`](approval.md).

## Commands

| Command | Does | Writes |
|---|---|---|
| `scan --project P` | Evaluates `catalog/stacks.yaml` rules (file, content regex, npm/maven/gradle/pip dependency, `implies`). Never follows symlinks; skips `.git`, `node_modules`, build dirs. | nothing |
| `select --project P [--tags a,b] [--init …]` | Proposes default packs + packs triggered by detected stacks; drops inactive skills; lists same-priority conflicts for the owner. | `.tareq/skills.yaml` only with `--init`, only if absent, never through a symlink |
| `sync --project P [--ref R \| --commit C]` | Dry-run plan + summary + fingerprint. | nothing |
| `sync … --apply F --commit C` | Recomputes the plan, asks a person to confirm it on the controlling terminal, then applies it. **Refused (exit 2) anywhere without a terminal.** | generated files, owned settings keys, lock, history |
| `rollback --project P --to REV [--apply F]` | Regenerates the exact state recorded by the lock at client revision `REV`; the same approval gate. | same as sync; never `.tareq/skills.yaml` |
| `recover --project P` | Repairs an interrupted sync/rollback by restoring the pre-sync state (or finishing cleanup of a completed one). Needs no approval: it only returns files to the state the owner already had. | restores files |
| `doctor --project P [--library S]` | Read-only: pending transaction, lock validity and forgery, hand-edited or missing generated files, stale config, personal-skill collisions, manual skills, OpenCode status, and (with `--library`) full lock-vs-catalog check. | nothing |
| `add-skill DIR --id … --category … --version … [--authored \| --url --commit --license]` | Copies a skill verbatim into `library/` with `SOURCE.txt` and adds a `candidate` / review-pending entry. Atomic; never executes content. Operates on the tareq-skills repo, not on a client project. | `library/`, `catalog/skills.yaml` |
| `note --project P --category C TEXT` | Appends a categorized note or lesson to `.tareq/history.md`. | `.tareq/history.md` (append only) |

Exit codes: 0 success · 1 failure or blocked plan · 2 approval unavailable or denied.
There is no `--home`, `--yes`, `--force`, or similar option, and option abbreviations are off.

Library source defaults to `catalog.repo` in the project config. The library is cloned into
`$TAREQ_CACHE` (default `~/.cache/tareq-skills`), outside the client repo, and checked out
detached at the exact commit. Every use verifies `HEAD` and a clean tree (D-21, R-14).

## Client project layout after sync

| Path | Owner | Notes |
|---|---|---|
| `.tareq/skills.yaml` | owner | Never written by sync or rollback |
| `.tareq/skills.lock` | tareq | Version 2: `generated` (path + hash of every generated file), `settings` (owned keys and list items per file, `created`, `file_hash`), `skills[].output_hash`, `plan_fingerprint`, `approval` (channel, approver, time), optional `rollback` |
| `.tareq/history.md` | append-only | Sync/rollback entries (with approver); owner notes and lessons |
| `.tareq/SKILLS-<category>.md` | tareq | Skill register with source links (read on demand) |
| `.tareq/.gitignore` | tareq | Ignores the two runtime entries below |
| `.tareq/.lock` | runtime | Empty `flock` file; not project state |
| `.tareq/.txn/` | runtime | Exists only during a sync/rollback or after an interruption |
| `.claude/rules/tareq-skills.md` | tareq | Short, always-loaded pointer (Claude; OpenCode via `instructions`) |
| `.claude/skills/<id>/` | tareq | Verbatim copies (frontmatter rewritten only for overlays, recorded by `output_hash`) |
| `.claude/settings.json` → `skillOverrides.<id>` | tareq key | Manual skills (`user-invocable-only`); other keys untouched |
| `opencode.json` → `permission.skill.<id>`, `instructions[]` | tareq keys | OpenCode: documented only, NOT TESTED |
| anything else | owner | Never read for writing, never removed |

## Transaction and recovery (R-19)

Every apply runs inside a durable journal (`bin/tareqlib/txn.py`):

1. Under the project lock, any earlier interrupted transaction is repaired first.
2. Every touched file is backed up under `.tareq/.txn/files/` (fsync'd), then `journal.json`
   is written atomically. No project file changes before the journal is durable.
3. Each write is temp file → fsync → rename → fsync of the directory.
4. Post-write verification (hashes of every output, each skill directory, the written lock).
5. A durable `COMMITTED` marker is the single commit point; then the directory is removed.

What is guaranteed, and what is only tested or not tested:

| Failure | Behavior | Evidence |
|---|---|---|
| Exception Python catches, at any step of a sync (48 in the test scenario) | Restored immediately to the exact pre-sync state | PASS: failure injected at every step before the commit marker; a failure after the marker is a completed sync |
| Process terminated (SIGKILL) at any step | A partially applied project **can exist until recovery runs**. The next locked command (`sync`/`rollback` apply, `note`, `recover`) restores the exact pre-sync state, or finishes a transaction whose commit marker was durable. Planning is blocked, and `doctor` reports `txn-pending`, until then | PASS: real SIGKILL at all 48 steps, then recovery; also SIGKILL during recovery at each of its 11 steps, then recovery again (idempotent) |
| Corrupt or malicious journal | Recovery refuses and leaves the project untouched: only tareq-owned paths are accepted and every backup is hash-checked | PASS (corrupt backup, owner-file path, `../` path, garbage) |
| Power loss or operating-system crash | fsync on files and directories is issued in the order above, but durability depends on the filesystem and device honoring fsync | **NOT TESTED**: cannot be simulated in this environment |
| Concurrent runs | Prevented by the lock below | PASS |

The earlier wording "no partial synchronization is ever left behind" applied only to caught
exceptions. The accurate claim is the table above.

## Locking (F1)

`sync --apply`, `rollback --apply`, `recover`, `note`, and `select --init` take an exclusive
`flock` on `.tareq/.lock`. A second operation is refused immediately (`ProjectBusy`) and
changes nothing. The kernel releases the lock when the holder exits, even if it is killed.
Planning and applying happen under one lock hold, so nothing can change between the
fingerprint check and the writes. `apply_plan` raises if called without the lock. The lock is
advisory, POSIX-only, and not reliable on network filesystems that do not implement `flock`.
The dry-run `sync`/`rollback` plan and `doctor` are read-only and take no lock.

## Ownership (F4, R-12, R-18)

What tareq-skills may ever claim, write, or delete is a fixed allowlist
(`validate_catalog.py`, "ownership"):

- files: `.claude/skills/<id>/…` where `<id>` is a skill registered in the same lock,
  `.claude/rules/tareq-skills.md`, `.tareq/SKILLS-<category>.md`, `.tareq/.gitignore`;
  plus `.tareq/skills.lock`, `.tareq/history.md`, and the two settings files for transactions;
- settings keys: `skillOverrides.<registered id> = "user-invocable-only"` in
  `.claude/settings.json`; `permission.skill.<registered id> = "ask"` and the `instructions`
  entry for the rules file in `opencode.json`.

A lock that claims anything else is rejected, as is a lock whose `output_hash` does not match
its listed files. Before an existing lock is trusted for removal or rollback, its skill files
are regenerated from the library at the lock's own commit and must match exactly, so a forged
but self-consistent lock cannot claim a manual skill. A settings file is deleted only if it was
created by tareq-skills and is byte-identical to what tareq-skills last wrote. A rollback target
lock read from git history is validated the same way, and its library must be the project's
configured one unless `--library` is passed explicitly.

## Other safeguards: implementation and tests

| ID | Implementation | Tests |
|---|---|---|
| R-12 | Writes only to absent paths or owned paths whose hash equals the lock. Unowned files, unowned keys, unmanaged files inside a skill dir, invalid JSON all block. Overwriting an unmanaged skill needs `--approve-overwrite <id>` (shown in the approved summary); `--adopt <id>` takes over identical bytes only. Nothing is written through a symlink. | `test_manager` `test_r12_*`; `test_security` `TestOwnershipForgery` |
| R-13 | Before every plan: same id in `~/.claude/skills`, `~/.config/opencode/skills`, `~/.agents/skills` (home from the passwd database, not `$HOME`), project `.opencode/skills` / `.agents/skills`, or a manual skill declaring that name → blocked. The probe is part of the fingerprint. | `TestCollisions`, `TestHomeAndSurface` |
| R-14 | Full 40-char commit only; checkout `HEAD` and clean tree verified. The library catalog is fully validated, including every content hash. Per-skill source hash checked before copying. After writing: every desired file, each skill directory, and the lock. Destination re-checked against the plan before the first write. | `TestHashesAndPinning`, `test_destination_changed_between_plan_and_write_is_refused` |
| R-15 / R-20 / D-26 | Dry-run summary and fingerprint; apply needs an `Approval` typed by a person on the controlling terminal and bound to the recomputed fingerprint (see `approval.md`). | `TestApprovalEnforcement`, `TestApprovalFingerprint`, `TestNoAlternatePaths` |
| R-16 | Disabled/candidate skills cannot be synced and stay in the catalog. Removal touches only owned, unmodified files. | `test_r16_*` |
| R-17 | Summary and doctor mark OpenCode output "documented only; NOT TESTED". | `TestReportingAndDoctor` |
| R-18 | Rollback uses the same ownership rules; a hand-edited owned file is left and reported; the config is never written; generated state must reproduce the target lock's hashes exactly. | `TestRollback`, `TestOwnershipForgery` |
| F5 | `note` and `select --init` refuse symlinks (including dangling), directories, and FIFOs; `note` appends (never rewrites); `--init` uses `O_EXCL` and never overwrites. | `TestSymlinkWrites` |

Mutation check: `python3 tests/mutation_check.py` disables each safeguard in a scratch copy and
requires its tests to fail (results in the project log).

## Live Claude Code check

`TAREQ_LIVE_CLAUDE=1 python3 -m unittest discover -s tests -p test_live_claude.py` syncs a
temp project and asks a real `claude -p` session which skills and rules it sees. It is
opt-in because it calls the model. OpenCode is not installed, so its output is documented only.

## Limitations

- Applying needs a person at a terminal (`approval.md`). The owner's iPhone + cloud-session
  environment cannot provide that; see decision O-15.
- Code that emulates a terminal can still satisfy the confirmation. Power-loss durability is
  NOT TESTED. The lock is advisory and POSIX-only.
- Settings files are rewritten as formatted JSON (2-space indent). Content outside owned keys
  is preserved, but the original formatting is not. JSONC (`opencode.json` with comments) is
  refused, not edited.
- Rollback needs the client project to be a git repository holding the earlier lock.
- `select` is rule-based (stacks, packs, tags). Task-aware AI recommendation is deferred.
- The manager skill (`tareq-skill/`) is not yet a catalog entry, so it is not distributed
  by sync. Cataloging it is part of seeding (M4).
- `add-skill` edits the tareq-skills repository and is not covered by the project lock.
