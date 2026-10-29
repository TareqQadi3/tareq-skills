# CLAUDE.md — tareq-skills

Instructions for any AI agent working in this repository. Read `docs/HANDOFF.md` first.
Full background: `docs/TAREQ-SKILLS-PROJECT-HANDOFF.md` (original handoff, do not edit).

## Communication

- Reply to the owner in **concise, clear Arabic**. Code, identifiers, and repository
  content are in English.
- The owner uses an iPhone and cannot run terminal commands. Do everything you can
  yourself; never ask the owner to run commands.
- Present choices **step by step**, one decision at a time, with a recommendation.
  Prefer multiple-choice questions.
- Report results as **PASS / FAIL / NOT TESTED** with evidence. Separate what was
  verified from what was not. Never claim unverified work.

## Models and agents

- Latest available **Opus** for architecture, planning, security, and complex reasoning.
  Latest available **Sonnet** for implementation, coding, and testing. Never pin a
  version number; always use the latest.
- Never claim a model was used without evidence. Subagents state their model ID on the
  first line of their reply; record it as "self-reported". The main session model is
  changed only by the owner (`/model`).
- Use parallel agents only when it helps, with **non-overlapping file ownership** and one
  coordinating agent that integrates and runs regression checks.

## Safety constraints (until the owner explicitly approves otherwise)

- Do **not** copy, import, move, install, disable, delete, or modify any existing skill
  (SMMS repo-level skills or user-level skills).
- Do **not** modify SMMS, Qeedha, Qeedha B, or any other project or repository.
- Do **not** import or install external skills, plugins, MCP servers, or tools, and do
  **not** execute scripts from external skill repositories.
- Do **not** push to `main`, merge, force-push, or rewrite history. All changes go to a
  `claude/*` branch and a Pull Request.
- Do **not** commit, print, or expose secrets, tokens, credentials, or private data.
- Do **not** deploy or make destructive changes.
- Ask before any step that involves a payment or paid service.
- Approval in one context does not extend to another.
- Verify official documentation before building any adapter; never rely on memory for
  tool paths or fields.

## Library rules

- Disabled skills are never deleted; they stay in the catalog with status `disabled`.
- Every imported skill has `SOURCE.txt` (origin URL, commit SHA, license, fetch date,
  content hash) and is pinned to a commit, never a floating branch.
- Imported skills are stored verbatim; local changes go in `catalog/overlays/`.
- Review `SKILL.md`, every script, and every reference file before activation.
  Offensive-security skills are restricted to isolated, owned environments.
- Every new skill's description cost is measured against the context budget before
  activation.
- Generated adapter output is never edited by hand.

## Working style

- For any task, choose the suitable skills, or give the owner the options with a
  comparison and a recommendation.
- No duplicate work, no repeated checks whose results are still valid, no research
  unrelated to the request.
- Keep milestones coherent; do not create work belonging to later milestones.
- Distinguish **approved**, **recommendation**, **open**, and **unverified** items.

## State and continuity

- `docs/HANDOFF.md`: current state and next actions. Update at the end of each milestone.
- `docs/project-log.md`: append meaningful milestones and results only.
- `docs/decisions.md`: record every owner decision; move items from Open to Approved.
- Conversation memory is not a source of truth; these files are.
