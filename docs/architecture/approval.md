# Approval enforcement (D-26)

Applying a sync or rollback to a project requires **explicit approval that the tool itself
verifies**. A plan fingerprint is an identifier. It is never proof of approval.

## How it works

1. `bin/tareq sync` (no `--apply`) is a dry run. It prints the change summary and the plan
   fingerprint, and writes nothing.
2. `bin/tareq sync --apply <fingerprint> --commit <sha>` recomputes the plan. If the
   fingerprint differs from the one passed, it stops (exit 1) before asking anyone.
3. The tool opens the **controlling terminal** (`/dev/tty`), not stdin or stdout, shows the
   full summary there, and asks the person to type `apply <first 12 hex digits of the
   fingerprint>`. Anything else, a timeout (300 s), or a closed terminal cancels (exit 2).
4. Under the project lock the plan is **recomputed again** and must still have exactly the
   approved fingerprint. The fingerprint covers the library source and commit, every source
   hash, the current state of every destination path, the personal-skill collision probe and
   OpenCode environment flags, the settings changes, the ordered operations, and the lock
   content. Any change after the person typed the phrase makes apply refuse (exit 2).
5. Inside the transaction the destination state is compared with the plan once more before
   any file is touched.
6. The approval (`channel`, `approver`, time) is written to `.tareq/skills.lock` and
   `.tareq/history.md`.

Library code enforces the same rule: `apply_plan` needs an `Approval` object from an accepted
channel whose fingerprint equals the plan's, and it needs the project lock held. Passing a
fingerprint string, an approval from an unknown channel, or an approval for another plan is
rejected. There is **no** flag, environment variable, or config option that skips, simulates, or
pre-answers the confirmation (`--yes`, `--force`, `--home`, `TAREQ_YES`, … do not exist, and
option abbreviations are disabled so `--approve` cannot mean `--approve-overwrite`).

## Which environments can provide enforceable approval

| Environment | Enforceable? | Evidence |
|---|---|---|
| A person at an interactive terminal who runs `bin/tareq` themselves (local shell, SSH with a pty, tmux/screen) | **Supported** | Tested with an emulated terminal (pty): PASS. A real person typing on a real device: NOT TESTED |
| The Claude Code **cloud / web / mobile** session this project is developed in (`CLAUDE_CODE_ENTRYPOINT=remote_mobile`) | **Unsupported: fails closed** | Run in this session: exit 2, `CLAUDECODE is set`; without the marker: exit 2, `no controlling terminal (No such device or address)`; nothing written |
| An agent's shell tool inside a terminal-based Claude Code session | **Unsupported: fails closed** by the `CLAUDECODE` marker (heuristic) | Marker refusal tested: PASS. The real terminal-based harness: NOT TESTED |
| CI, cron, `docker run` without `-t`, pipes, `yes \| tareq …` | **Unsupported: fails closed** | Tested: no controlling terminal → exit 2, nothing written |
| An agent or script that **allocates its own pseudo-terminal** and types the phrase | **Not defended** | Known limitation, see below |
| Windows | Unsupported (needs `/dev/tty` and `fcntl`) | NOT TESTED |
| OpenCode sessions | Unknown | OpenCode is not installed; how its shell tool treats the controlling terminal is not documented. NOT TESTED |

## What this does and does not protect against

- It protects against a plan being applied by an unattended or non-interactive caller, by a
  copied fingerprint, by scripted input, by a stale or tampered plan, and by option typos.
- It does **not** stop code that deliberately emulates a terminal (for example Python's `pty`
  module or `script`/`expect`) or that edits the tool itself. The `CLAUDECODE` check is a
  heuristic that can be unset; it adds friction and clearer messages, not security.
- Real protection against a determined agent needs an approval channel outside the agent's
  execution environment (below). None is implemented.

## Consequence for the owner

The owner works from an iPhone through Claude Code cloud sessions. **That environment cannot
satisfy the approval check, so `--apply` is refused there by design.** Plans can be created and
reviewed from the phone, but applying needs a terminal the owner controls. Until an
out-of-band channel is chosen (open decision O-15), milestones that apply changes to a project
(M5, the SMMS pilot) cannot run end to end from the phone.

## Candidate out-of-band channels (not implemented; decision O-15)

| Option | How approval would be established | Trade-offs |
|---|---|---|
| Run `--apply` on a computer the owner controls | The existing terminal channel | Works today; needs a computer with git, Python, and a clone of the client repo |
| One-time code shown only to the owner | The tool shows a code through a channel the agent cannot read (push notification, email) and the owner types it back | Needs a notification service and the owner's contact details; adds an external dependency |
| Time-based one-time password on the owner's phone | An authenticator app code bound to the plan | The shared secret must be stored where the agent cannot read it, which is not true of a cloud session |
| Merge of a plan file by the owner on GitHub | The plan fingerprint is committed on a branch; the tool applies only when it is on the default branch via the owner's merge | Depends on branch protection (not yet configured) and GitHub access from the tool |
