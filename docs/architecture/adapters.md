# Agent integration: Claude Code and OpenCode (M2)

Adapter requirements derived from official documentation and local probes, plus owner
safeguards (D-22). Implementation is M3. Labels: **[doc]** stated in official docs · **[probe]** observed in a local
Claude Code run (see Evidence) · **[unverified]** not documented or not tested.

## Sources (read 2026-10-30)

| Tool | Source |
|---|---|
| Claude Code | https://code.claude.com/docs/en/skills · /memory · /hooks · /settings · /plugins · /plugin-marketplaces (`.md` variants) |
| OpenCode | `opencode.ai` is blocked by the session network policy (HTTP 403 at the proxy). Read the official docs **source** in `github.com/sst/opencode`, branch `dev`, commit `237a847056522ec78a5c64ab7db5a19736e1ea58`: `packages/web/src/content/docs/{skills,rules,config,agents,permissions,commands}.mdx` |

Claude Code docs describe the current release; local probes used Claude Code 2.1.312.
OpenCode was not installed or run (no external tool installs, D-04).

## Verified behavior

### Skill locations and discovery

| | Claude Code | OpenCode |
|---|---|---|
| Project | `.claude/skills/<name>/SKILL.md`, from cwd up to the repo root; nested dirs load on first file access [doc] | `.opencode/skills/`, **`.claude/skills/`**, `.agents/skills/`, walking up to the git worktree root [doc] |
| User | `~/.claude/skills/` (not in cloud/Cowork sessions) [doc] | `~/.config/opencode/skills/`, `~/.claude/skills/`, `~/.agents/skills/` [doc] |
| Same name in two places | Enterprise > personal > **project**; plugin skills are namespaced; synced claude.ai skills yield to project skills [doc] | "Ensure skill names are unique across all locations"; precedence **not documented** [unverified] |
| Symlinked skill folder | Supported in enterprise/personal/project locations [doc][probe] | Not documented [unverified] |
| Live reload | Watches skill dirs within a session [doc] | Not documented [unverified] |
| Cloud sessions | Committed project `.claude/skills/` loads. Personal skills don't. Plugins declared in the repo's `.claude/settings.json` **don't load** [doc] | n/a |
| Opt-out | — | `OPENCODE_DISABLE_CLAUDE_CODE=1` or `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` stop reading `.claude/skills` [doc] |

### `SKILL.md` frontmatter

| Field | Claude Code | OpenCode |
|---|---|---|
| `name` | Optional; defaults to the dir name; no lowercase rule [doc] | **Required**; `^[a-z0-9]+(-[a-z0-9]+)*$`, 1–64 chars, **must equal the dir name** [doc] |
| `description` | Recommended. Listing caps `description` + `when_to_use` at 1,536 chars (configurable) [doc] | **Required**, 1–1024 chars [doc] |
| `license`, `compatibility`, `metadata` | Accepted, not acted on [doc] | Accepted; `metadata` is a string→string map [doc] |
| `when_to_use`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `paths`, `model`, `hooks`, `context`, … | Supported [doc] | Ignored as unknown fields [doc] |

Portable subset: `name`, `description`, `license`, `compatibility`, `metadata`.

### Invocation control and context cost

| | Claude Code | OpenCode |
|---|---|---|
| Listing in context | Name + description per skill. The listing budget is 1% of the context window; the least-used descriptions are dropped first [doc] | Every permitted skill is listed in the `skill` tool description [doc] |
| Manual-only without editing `SKILL.md` | `.claude/settings.json` → `skillOverrides: {"<name>": "user-invocable-only"}` removes it from the listing [doc][probe]. `"name-only"` keeps the name only [doc] | `opencode.json` → `permission.skill.<name>: "ask"` prompts before loading, but the skill **stays listed** [doc]. `"deny"` hides it [doc] |
| Manual-only in frontmatter | `disable-model-invocation: true` [doc][probe] | No equivalent [doc] |

### Project instructions

| | Claude Code | OpenCode |
|---|---|---|
| Primary file | `CLAUDE.md` (cwd and parents, concatenated) [doc][probe] | `AGENTS.md`; falls back to `CLAUDE.md` when no `AGENTS.md` exists [doc] |
| `AGENTS.md` | Read only when no `CLAUDE.md`/`CLAUDE.local.md` exists (v2.1.277+), unless a setting says otherwise [doc][probe] | Primary [doc] |
| Extra files without editing the primary file | `.claude/rules/*.md` always loads (unless it has `paths`) [doc][probe] | `instructions: [...]` in `opencode.json`; globs and URLs allowed [doc] |
| Session-start injection | `SessionStart` command hook; its stdout is added to context [doc] | Not reviewed [unverified] |

## Common integration model

One resolved set per project (`.tareq/skills.yaml` → `.tareq/skills.lock`, M1). The sync
step (M3, only after owner approval) generates the following in the client repo:

| Output | Read by | Purpose |
|---|---|---|
| `.claude/skills/<id>/` — **verbatim** copy of `library/<category>/<id>/` | Claude Code and OpenCode (shared path) | Skills. One physical copy, no per-tool duplicates |
| `.claude/settings.json` → `skillOverrides` entries owned by tareq-skills | Claude Code | Manual-only and name-only skills without editing `SKILL.md` |
| `opencode.json` → `permission.skill` and `instructions` entries owned by tareq-skills | OpenCode | Manual skills (`ask`); instruction wiring |
| `.claude/rules/tareq-skills.md` | Claude Code directly; OpenCode via `instructions` | Project skill register and categorized instructions (owner requirement §4-B) |

The project's own `CLAUDE.md` and `AGENTS.md` are never modified.

## Adapter requirements for M3

| ID | Requirement | Basis |
|---|---|---|
| R-01 | Generate skills only into `.claude/skills/<id>/`. Do not also write `.opencode/skills/` or `.agents/skills/`. | OpenCode reads `.claude/skills`; duplicate names are unsupported |
| R-02 | Copy content verbatim. The generated directory must hash to the catalog `content_hash` (M1 algorithm). Copies, not symlinks, so cloud sessions get committed files and OpenCode symlink handling doesn't matter. | Probe: verbatim copy hash = catalog hash; symlinks unverified in OpenCode |
| R-03 | Catalog `id`, skill directory name, and `SKILL.md` frontmatter `name` must be identical. Skills that break this cannot target OpenCode. | OpenCode name rule |
| R-04 | For an `opencode` target, `description` must be 1–1024 chars. Put the key use first (Claude truncates at 1,536 with `when_to_use`). | Both docs |
| R-05 | Apply `invocation: manual` via `skillOverrides` (Claude) and `permission.skill: ask` (OpenCode), not by rewriting `SKILL.md`. | Docs + probe |
| R-06 | Description budget (D-14): for Claude, count skills listed with a description. For OpenCode, count **every** generated skill not denied, since `ask` skills stay listed. | Listing behavior differs |
| R-07 | Overlays that change `description`, `when_to_use`, or `paths` require a rewritten `SKILL.md`. The lock must then record the generated file hash next to the source `content_hash` (lock schema change in M3). `when_to_use` and `paths` affect Claude only. | Frontmatter support differs |
| R-08 | Merge only tareq-owned keys into existing `.claude/settings.json` and `opencode.json`. Record the generated files and owned keys in the lock so rollback and removal are exact. Never touch the project's `CLAUDE.md`/`AGENTS.md`. | Avoid clobbering project config |
| R-09 | Preflight: detect name collisions with personal skills (`~/.claude/skills`, `~/.config/opencode/skills`, `~/.agents/skills`) and project `.opencode/skills`, `.agents/skills`. A personal skill with the same name **shadows** the project copy in Claude Code. Warn when `OPENCODE_DISABLE_CLAUDE_CODE*` is set. | Precedence rules |
| R-10 | Review gate (M4): flag `allowed-tools`, `hooks`, `model`, `context: fork`, and `` !`command` `` injection in imported skills. These grant capabilities in Claude Code and are silently ignored by OpenCode. | Security; behavior differs |
| R-11 | Rollback = restore the previous lock and regenerate, or `git revert` the sync commit in the client repo. Either gives the same files because output is deterministic. | M1 lock design |

### Owner safeguards (D-22)

| ID | Requirement |
|---|---|
| R-12 | Never overwrite or delete a project skill or file that the lock does not record as tareq-generated. Any change to such a file needs explicit owner approval for that file. |
| R-13 | Name-collision detection (R-09) runs before every sync. Any collision **blocks** the sync until the owner decides. |
| R-14 | Every sync is pinned to an exact 40-char library commit. Content hashes are verified on the fetched source before copying, and on the written files after copying. Any mismatch aborts with no partial write. |
| R-15 | Sync runs as a dry run first. It shows a change summary: skills added, updated, or removed; owned settings keys; budget before and after; collisions. Apply requires approval of that exact summary: the apply step must present the summary's hash and refuses if the plan changed. |
| R-16 | Disabled skills stay in the catalog. Removing a generated skill from a project happens only for tareq-owned files, only through an approved plan. Manually maintained project files are never touched. |
| R-17 | Reports label OpenCode results **documented** (from docs) or **tested** (executed). Untested OpenCode behavior is never reported as PASS. |
| R-18 | Rollback restores or removes only files and settings keys that the lock proves were generated and owned by tareq-skills (path + recorded output hash). Anything else, including a generated file edited by hand since the last sync, is left untouched and reported. (D-24) |
| R-19 | Sync is atomic. Every touched path is backed up before writing, and validation runs after writing. Any failure restores the exact pre-sync state: bytes, presence, and owned settings keys. No partial sync is ever left behind. (D-24) |
| R-20 | Approval is bound to an immutable plan fingerprint: a hash over the library commit, source content hashes, the destination's current state (hash of every path the plan touches, including absence), and the ordered operation list. Apply recomputes it and refuses on any difference; a new plan and approval are then required. (D-24) |

## Limitations

- OpenCode behavior is from its docs source only; nothing was executed. Precedence on
  duplicate names, symlink handling, and live reload are undocumented.
- `opencode.ai` remains blocked by the network policy; the GitHub docs source may differ
  from the published site.
- Probes ran in a non-interactive session (`claude -p`). The model reported which skills
  and instruction markers it saw. That is observational evidence, not an API guarantee.
- `claude plugin validate .claude/skills` reported no components and did not flag malformed
  frontmatter in this environment, so it is **not** usable as a conformance check.
- OpenCode `ask` keeps descriptions in context, so manual skills still cost context there.

## Evidence (2026-10-30, Claude Code 2.1.312, temporary dirs, deleted afterwards)

| Probe | Result |
|---|---|
| Verbatim copy of a fixture skill into `.claude/skills/` hashes equal to its catalog `content_hash` | PASS |
| Copied skill listed by Claude Code | PASS |
| Skill reached through a symlinked folder listed | PASS |
| `disable-model-invocation: true` skill absent from the listing | PASS |
| `skillOverrides: user-invocable-only` in project `.claude/settings.json` hides the skill | PASS |
| With `CLAUDE.md` + `.claude/rules/x.md` + `AGENTS.md`: CLAUDE.md and the rules file loaded, AGENTS.md not loaded | PASS |
| Without `CLAUDE.md`: rules file and `AGENTS.md` loaded | PASS |
| Any OpenCode behavior | NOT TESTED (not installed) |
