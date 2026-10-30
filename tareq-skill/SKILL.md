---
name: tareq-skill
description: Manage a project's skills with the tareq-skills library - detect the stack, propose the smallest suitable skill set, plan a pinned sync, show the change summary, apply only the owner-approved plan fingerprint, check health, roll back, and record notes and lessons. Use when the user asks which skills a project should use, to add, update, remove, or roll back project skills, or to check skill conflicts, collisions, or context budget.
license: Proprietary (internal / authored, D-23)
compatibility: claude-code, opencode
---

# tareq-skill — project skill manager

The tool is `bin/tareq` in the tareq-skills repository (Python 3, PyYAML, jsonschema).
Rules and requirements: `CLAUDE.md`, `docs/architecture/manager.md`, `docs/architecture/adapters.md`.

## Owner rules (always)

- Reply to the owner in concise Arabic; present one decision at a time with a recommendation.
- Report results as PASS / FAIL / NOT TESTED with evidence. OpenCode behavior that was not
  executed is "documented only — NOT TESTED", never PASS.
- Never change a project without an approved plan. Never push to `main`, merge, or deploy.

## Workflow

1. **Scan**: `bin/tareq scan --project <dir>` lists detected stacks with evidence.
2. **Select**: `bin/tareq select --project <dir>` proposes packs and skills.
   - Same-priority conflicts are listed under `needs_owner_decision`. Ask the owner; never choose.
   - `--init --repo <url> --ref <tag>` writes `.tareq/skills.yaml` only if it does not exist.
3. **Plan**: `bin/tareq sync --project <dir> [--ref <tag> | --commit <sha>]` is a dry run.
   - Show the owner the full summary: skills added/updated/removed, budget, settings changes,
     anything left untouched, and every `BLOCKED` line.
   - A blocked plan cannot be applied. Explain each block and let the owner decide.
4. **Apply**: only after the owner approves that exact summary, run the printed command:
   `--apply <fingerprint> --commit <sha>`.
   - If anything changed since the plan, apply refuses. Re-plan and ask again.
5. **Doctor**: `bin/tareq doctor --project <dir> [--library <src>]` is a read-only health check.
6. **Rollback**: `bin/tareq rollback --project <dir> --to <git-rev>` plans; `--apply <fingerprint>` applies.
   - It restores only tareq-owned files and settings, never `.tareq/skills.yaml`.
7. **Record**: `bin/tareq note --project <dir> --category <decisions|lessons|...> "<text>"`.
8. **New skill**: `bin/tareq add-skill <dir> --id ... --category ... --version ...`.
   - Use `--authored` for skills written here.
   - Third-party skills need `--url`, `--commit`, and `--license`, plus owner approval to import.
   - Every new skill enters as `candidate` with review pending. Activation needs a security,
     license, and overlap review and the owner's approval.

## Never

- Edit generated skills or `.tareq/skills.lock` by hand.
- Use `--approve-overwrite` without the owner's explicit approval for that skill.
- Run scripts from a skill during intake or review.
