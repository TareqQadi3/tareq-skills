#!/usr/bin/env python3
"""Mutation check for the M3 security fixes.

For each mutation this script copies bin/, tests/, catalog/ and templates/ to a scratch
directory, re-introduces one specific defect (disables one safeguard), and runs the tests that
are supposed to catch it. A mutation is DETECTED when those tests fail and SURVIVED when they
still pass (which means the tests do not really protect that safeguard). It never modifies the
working tree.

Usage: python3 tests/mutation_check.py [--only SUBSTRING] [--list]
Exit code 1 if any mutation survived or a baseline run failed.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEC = "tests.test_security."
MAN = "tests.test_manager."
CRASH = SEC + "TestCrashRecovery."
EVERY_STEP = CRASH + "test_sigkill_at_every_step_recovers_to_pre_state_or_completed_state"

# (name, [(file, old, new), ...], [test selectors that must fail])
MUTATIONS = [
    # --- approval (D-26, R-15, R-20)
    ("approval: fingerprint binding ignored",
     [("bin/tareqlib/approval.py", "    if approval.fingerprint != fingerprint:", "    if False:")],
     [MAN + "TestApprovalFingerprint", SEC + "TestApprovalEnforcement.test_destination_change_while_prompt_is_open_invalidates_approval"]),
    ("approval: any channel accepted",
     [("bin/tareqlib/approval.py", "    if approval.channel not in ACCEPTED_CHANNELS:", "    if False:")],
     [SEC + "TestApprovalEnforcement.test_fingerprint_alone_is_never_approval"]),
    ("approval: CLI applies without asking a person",
     [("bin/tareqlib/cli.py", '    approval = _approve(plan, "synchronize this project")',
       '    approval = approval_mod.Approval(plan.fingerprint, "tty", "nobody", "2026-01-01T00:00:00Z")')],
     [SEC + "TestApprovalEnforcement.test_no_controlling_terminal_fails_closed",
      SEC + "TestApprovalEnforcement.test_wrong_confirmation_is_denied",
      SEC + "TestNoAlternatePaths.test_only_approval_gated_cli_functions_reach_apply"]),
    ("approval: rollback applies without asking a person",
     [("bin/tareqlib/cli.py", '    approval = _approve(plan, f"roll back this project to {a.to}")',
       '    approval = approval_mod.Approval(plan.fingerprint, "tty", "nobody", "2026-01-01T00:00:00Z")')],
     [SEC + "TestApprovalEnforcement.test_rollback_apply_needs_a_terminal_and_confirmation"]),
    ("approval: confirmation phrase not checked",
     [("bin/tareqlib/approval.py", "        if typed != phrase:", "        if False:")],
     [SEC + "TestApprovalEnforcement.test_wrong_confirmation_is_denied"]),
    ("approval: agent-harness marker ignored",
     [("bin/tareqlib/approval.py", 'AGENT_ENV_MARKERS = ("CLAUDECODE",)', "AGENT_ENV_MARKERS = ()")],
     [SEC + "TestApprovalEnforcement.test_agent_harness_marker_refuses_even_with_a_terminal"]),
    ("approval: stale fingerprint not rejected before prompting",
     [("bin/tareqlib/cli.py", "    if plan.fingerprint != a.apply:\n        print(\"error: the plan changed since it was shown (fingerprint mismatch); nothing was \"\n              f\"applied. Current fingerprint: {plan.fingerprint}\", file=sys.stderr)\n        return 1\n    approval = _approve(plan, \"synchronize",
       "    if False:\n        return 1\n    approval = _approve(plan, \"synchronize")],
     [SEC + "TestApprovalEnforcement.test_stale_fingerprint_rejected_before_any_prompt"]),
    ("approval: summary not sanitized for the terminal",
     [("bin/tareqlib/approval.py", '            os.write(fd, sanitize_for_terminal(prompt).encode("utf-8"))', '            os.write(fd, prompt.encode("utf-8"))')],
     [SEC + "TestApprovalPrompt.test_summary_cannot_inject_terminal_control_sequences"]),
    ("approval: terminal hangup crashes instead of denying",
     [("bin/tareqlib/approval.py", "        except OSError as exc:  # hangup / I/O error on the terminal", "        except ZeroDivisionError as exc:  # hangup / I/O error on the terminal")],
     [SEC + "TestApprovalPrompt.test_terminal_io_error_is_a_denial_not_a_crash"]),
    ("approval: no timeout",
     [("bin/tareqlib/approval.py", "                if remaining <= 0:\n                    raise ApprovalDenied(\"approval timed out", "                if False:\n                    raise ApprovalDenied(\"approval timed out")],
     [SEC + "TestApprovalPrompt.test_timeout_is_a_denial"]),
    ("surface: recover creates .tareq in a non-tareq directory",
     [("bin/tareqlib/workflow.py", "    if not (project / \".tareq\").is_dir():\n        return None  # not a tareq project", "    if False:\n        return None  # not a tareq project")],
     [SEC + "TestApprovalPrompt.test_recover_on_a_non_tareq_directory_creates_nothing"]),
    ("approval: abbreviated flags accepted",
     [("bin/tareqlib/cli.py", "allow_abbrev=False, **kw", "allow_abbrev=True, **kw")],
     [SEC + "TestApprovalEnforcement.test_no_flag_or_environment_variable_skips_approval"]),
    # --- F1 locking
    ("lock: flock removed",
     [("bin/tareqlib/lock.py", "            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)", "            pass")],
     [SEC + "TestProjectLock"]),
    ("lock: apply_plan does not require the lock",
     [("bin/tareqlib/sync.py", "    lock_mod.assert_held(project)\n", "")],
     [SEC + "TestProjectLock.test_apply_plan_refuses_to_run_without_the_project_lock"]),
    ("lock: note runs unlocked",
     [("bin/tareqlib/workflow.py", "    with lock_mod.project_lock(project):\n        txn.recover(project)\n        try:\n            dest = safe_dest(project, HISTORY_FILE)",
       "    if True:\n        txn.recover(project)\n        try:\n            dest = safe_dest(project, HISTORY_FILE)")],
     [SEC + "TestProjectLock.test_mutating_operations_are_refused_while_another_process_holds_the_lock"]),
    # --- F2 journal / recovery
    ("txn: recovery does nothing",
     [("bin/tareqlib/txn.py", "    journal = _load_journal(project)\n    entries = journal[\"entries\"]", "    return None")],
     [EVERY_STEP]),
    ("txn: backups are not written",
     [("bin/tareqlib/txn.py", "                write_durable(backup, data)", "                pass")],
     [EVERY_STEP]),
    ("txn: committed transaction is rolled back",
     [("bin/tareqlib/txn.py", "    if (txn / COMMITTED).exists():\n        _discard(project)\n        return \"committed\"", "    if False:\n        return \"committed\"")],
     [EVERY_STEP]),
    ("txn: caught failures are not rolled back",
     [("bin/tareqlib/sync.py", "        outcome = tx.abort()", "        outcome = None")],
     [MAN + "TestAtomicity.test_caught_failure_at_every_step_restores_exact_state"]),
    ("txn: created directories are left behind",
     [("bin/tareqlib/txn.py", "    for d in reversed(journal[\"created_dirs\"]):\n        path = project / d", "    for d in []:\n        path = project / d")],
     [EVERY_STEP]),
    ("txn: file fsync removed",
     [("bin/tareqlib/fsutil.py", "            os.fsync(fh.fileno())", "            pass")],
     [CRASH + "test_writes_are_fsynced_files_and_directories"]),
    ("txn: directory fsync removed",
     [("bin/tareqlib/fsutil.py", "    fd = os.open(path, os.O_RDONLY | getattr(os, \"O_DIRECTORY\", 0))\n    try:\n        os.fsync(fd)", "    fd = os.open(path, os.O_RDONLY | getattr(os, \"O_DIRECTORY\", 0))\n    try:\n        pass")],
     [CRASH + "test_writes_are_fsynced_files_and_directories"]),
    ("txn: pending transaction does not block planning",
     [("bin/tareqlib/sync.py", "    if txn.pending(project):\n        blocks.append(", "    if False:\n        blocks.append(")],
     [CRASH + "test_note_and_next_plan_never_build_on_a_half_applied_state"]),
    ("txn: journal paths not restricted to tareq-owned paths",
     [("bin/tareqlib/txn.py", "    if not v.is_touchable_path(rel):", "    if False:")],
     [CRASH + "test_forged_journal_with_its_own_backup_cannot_write_owner_or_outside_files"]),
    ("txn: backup integrity not verified",
     [("bin/tareqlib/txn.py", "or sha256_bytes(backup.read_bytes()) != e[\"before\"]", "or False")],
     [CRASH + "test_corrupt_or_malicious_journal_leaves_the_project_untouched"]),
    ("txn: note does not recover first",
     [("bin/tareqlib/workflow.py", "    with lock_mod.project_lock(project):\n        txn.recover(project)\n        try:\n            dest = safe_dest(project, HISTORY_FILE)", "    with lock_mod.project_lock(project):\n        try:\n            dest = safe_dest(project, HISTORY_FILE)")],
     [CRASH + "test_note_and_next_plan_never_build_on_a_half_applied_state"]),
    # --- F3 home / surface
    ("surface: --home re-added to the CLI",
     [("bin/tareqlib/cli.py", '        p.add_argument("--apply", metavar="FINGERPRINT",', '        p.add_argument("--home", type=Path)\n        p.add_argument("--apply", metavar="FINGERPRINT",')],
     [SEC + "TestHomeAndSurface.test_home_option_is_not_part_of_the_public_cli"]),
    ("surface: collision home comes from $HOME",
     [("bin/tareqlib/fsutil.py", "    return Path(pwd.getpwuid(os.getuid()).pw_dir)", "    return Path(os.environ.get(\"HOME\") or pwd.getpwuid(os.getuid()).pw_dir)")],
     [SEC + "TestHomeAndSurface.test_collision_check_ignores_the_home_environment_variable"]),
    ("surface: environment not part of the fingerprint",
     [("bin/tareqlib/sync.py", '        "environment": environment,', '        "environment": [],')],
     [SEC + "TestHomeAndSurface.test_environment_is_part_of_the_plan_fingerprint"]),
    # --- F4 ownership
    ("ownership: generated-path allowlist off",
     [("bin/validate_catalog.py", "    return clean_segments(rel) and _GENERATED_RE.match(rel) is not None", "    return True")],
     [SEC + "TestOwnershipForgery"]),
    ("ownership: settings-key allowlist off",
     [("bin/validate_catalog.py", "def owned_key_allowed(file: str, key: tuple, value, skill_ids: set[str]) -> bool:\n", "def owned_key_allowed(file: str, key: tuple, value, skill_ids: set[str]) -> bool:\n    return True\n")],
     [SEC + "TestOwnershipForgery.test_claiming_a_user_setting_is_rejected",
      SEC + "TestOwnershipForgery.test_claiming_an_unregistered_or_wrongly_valued_override_is_rejected"]),
    ("ownership: skill directory need not be registered in the lock",
     [("bin/validate_catalog.py", "        if sid not in ids:\n            err(\"ownership-forged\", f\"'{path}' is in skill directory", "        if False:\n            err(\"ownership-forged\", f\"'{path}' is in skill directory")],
     [SEC + "TestOwnershipForgery.test_claiming_a_manual_skill_directory_is_rejected"]),
    ("ownership: output_hash consistency not checked",
     [("bin/validate_catalog.py", "        elif mapping_hash_of(mine) != e[\"output_hash\"]:", "        elif False:")],
     [SEC + "TestOwnershipForgery.test_inconsistent_output_hash_is_rejected"]),
    ("ownership: lock not corroborated against the library",
     [("bin/tareqlib/sync.py", "    if lock is not None and verify_lock is not None:", "    if False:")],
     [SEC + "TestOwnershipForgery.test_registering_and_claiming_a_manual_skill_fails_library_corroboration"]),
    ("ownership: settings file deleted even if edited since we wrote it",
     [("bin/tareqlib/sync.py", '        elif result == {} and created and prev.get("file_hash") == cur_state:', '        elif result == {} and created:')],
     [SEC + "TestOwnershipForgery.test_settings_file_created_by_us_is_deleted_only_if_untouched"]),
    ("ownership: rollback target lock not checked for forgery",
     [("bin/tareqlib/workflow.py", "    if forged:  # a rollback target from git history is untrusted input (F4)", "    if False:")],
     [SEC + "TestOwnershipForgery.test_rollback_target_lock_with_forged_claims_is_refused"]),
    ("ownership: rollback trusts the library named by an old lock",
     [("bin/tareqlib/workflow.py", '    if source is None and target["catalog"]["repo"] != trusted:', "    if False:")],
     [SEC + "TestOwnershipForgery.test_rollback_does_not_trust_a_library_named_by_an_old_lock"]),
    # --- F5 symlinks
    ("symlinks: note follows symlinks",
     [("bin/tareqlib/workflow.py", "            dest = safe_dest(project, HISTORY_FILE)\n        except UnsafePathError as exc:\n            raise SyncError(str(exc)) from exc\n        try:\n            fd = os.open(dest, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW\n                         | os.O_NONBLOCK",
       "            dest = project / HISTORY_FILE\n        except UnsafePathError as exc:\n            raise SyncError(str(exc)) from exc\n        try:\n            fd = os.open(dest, os.O_WRONLY | os.O_APPEND | os.O_CREAT\n                         | os.O_NONBLOCK")],
     [SEC + "TestSymlinkWrites.test_note_refuses_a_symlinked_history_file",
      SEC + "TestSymlinkWrites.test_note_refuses_a_dangling_symlink"]),
    ("symlinks: note can block on a FIFO",
     [("bin/tareqlib/workflow.py", "                         | os.O_NONBLOCK | getattr(os, \"O_CLOEXEC\", 0), 0o644)  # NONBLOCK", "                         | getattr(os, \"O_CLOEXEC\", 0), 0o644)  # NONBLOCK")],
     [SEC + "TestSymlinkWrites.test_note_does_not_block_on_a_fifo"]),
    ("symlinks: select --init follows symlinks and overwrites",
     [("bin/tareqlib/workflow.py", "            dest = safe_dest(project, CONFIG_FILE)\n        except UnsafePathError as exc:\n            raise SyncError(str(exc)) from exc\n        try:\n            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW",
       "            dest = project / CONFIG_FILE\n        except UnsafePathError as exc:\n            raise SyncError(str(exc)) from exc\n        try:\n            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC")],
     [SEC + "TestSymlinkWrites.test_init_refuses_dangling_and_live_symlinks_and_existing_files",
      SEC + "TestSymlinkWrites.test_cli_select_init_cannot_write_through_a_symlink"]),
    ("symlinks: note rewrites instead of appending",
     [("bin/tareqlib/workflow.py", "os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW\n                         | os.O_NONBLOCK", "os.O_WRONLY | os.O_TRUNC | os.O_CREAT | os.O_NOFOLLOW\n                         | os.O_NONBLOCK")],
     [SEC + "TestSymlinkWrites.test_note_appends_and_never_rewrites_existing_history"]),
    # --- M4 provenance for authored skills
    ("intake: authored skill provenance not recorded",
     [("bin/tareqlib/workflow.py", '                        **({"url": url, "commit": commit} if url and commit else {})}', '                        }')],
     [MAN + "TestIntake.test_authored_skill_can_record_where_it_was_derived_from"]),
    # --- M4 scanner fix
    ("scan: skill directories are scanned as project files",
     [("bin/tareqlib/fsutil.py", '                        ".claude", ".opencode", ".agents"})', '                        })')],
     [MAN + "TestScanAndSelect.test_skill_directories_are_not_part_of_the_project"]),
    # --- earlier safeguards that this change touched
    ("R-13: personal-skill collisions not detected",
     [("bin/tareqlib/sync.py", "            if (base / sid).exists() or (base / sid).is_symlink():", "            if False:")],
     [MAN + "TestCollisions"]),
    ("R-12: unmanaged files may be overwritten",
     [("bin/tareqlib/sync.py", "        elif skill and skill in approve_overwrite:", "        elif True:")],
     [MAN + "TestOwnership.test_r12_existing_unmanaged_skill_blocks"]),
    ("R-14: post-write verification skipped",
     [("bin/tareqlib/sync.py", "        _verify_after_write(project, plan, checkout_catalog, config)", "        pass")],
     [MAN + "TestHashesAndPinning.test_post_write_corruption_restores_everything"]),
    ("R-18: edited owned files are deleted on removal",
     [("bin/tareqlib/sync.py", "        if cur == recorded:\n            ops.append({\"op\": \"delete\"", "        if cur is not None:\n            ops.append({\"op\": \"delete\"")],
     [MAN + "TestOwnership.test_r16_hand_edited_owned_file_left_when_skill_removed"]),
    ("R-20: destination change between plan and write not refused",
     [("bin/tareqlib/txn.py", "            if path_state(self.project, rel) != state:\n                raise TransactionError", "            if False:\n                raise TransactionError")],
     [SEC + "TestApprovalEnforcement.test_destination_changed_between_plan_and_write_is_refused"]),
    ("R-20: destination state not part of the fingerprint",
     [("bin/tareqlib/sync.py", '        "destination": destination,', '        "destination": {},')],
     [MAN + "TestApprovalFingerprint.test_r20_fingerprint_binds_destination_state",
      SEC + "TestApprovalEnforcement.test_history_or_lock_change_invalidates_approval_even_if_operations_are_unchanged"]),
]


def run(mutation, scratch_root: Path) -> tuple[str, str]:
    name, edits, selectors = mutation
    work = Path(tempfile.mkdtemp(dir=scratch_root))
    for sub in ("bin", "tests", "catalog", "templates"):
        shutil.copytree(ROOT / sub, work / sub, ignore=shutil.ignore_patterns("__pycache__"))
    for rel, old, new in edits:
        path = work / rel
        text = path.read_text()
        if text.count(old) != 1:
            return "ERROR", f"pattern not found exactly once in {rel}: {old[:70]!r}"
        path.write_text(text.replace(old, new))
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env["TAREQ_CACHE"] = str(work / ".cache")
    proc = subprocess.run([sys.executable, "-m", "unittest", *selectors], cwd=work, env=env,
                          capture_output=True, text=True, timeout=1200)
    shutil.rmtree(work, ignore_errors=True)
    tail = [line for line in proc.stderr.splitlines() if line.startswith(("FAIL", "ERROR", "Ran", "OK"))]
    return ("DETECTED" if proc.returncode != 0 else "SURVIVED"), "; ".join(tail[-3:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="run mutations whose name contains this text")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    chosen = [m for m in MUTATIONS if not args.only or args.only.lower() in m[0].lower()]
    if args.list:
        for m in chosen:
            print(m[0])
        return 0
    scratch = Path(tempfile.mkdtemp(prefix="tareq-mutation-"))
    bad = 0
    try:
        for mutation in chosen:
            status, detail = run(mutation, scratch)
            print(f"{status:9} {mutation[0]}" + (f"   [{detail}]" if status != "DETECTED" else ""), flush=True)
            bad += status != "DETECTED"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"\n{len(chosen) - bad}/{len(chosen)} mutations detected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
