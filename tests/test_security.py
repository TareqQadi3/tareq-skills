"""Security regression tests for the M3 review fixes (F1-F6) and the approval gate (D-26).

Covers: tool-enforced approval (real controlling-terminal emulation via a pty), project
locking, journaled crash recovery with real SIGKILL at every step, ownership-forgery
rejection, symlink-write rejection, and the CLI/home surface. Each safeguard is also
mutation-checked by tests/mutation_check.py.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "tests"))

import validate_catalog as v  # noqa: E402
from ptyutil import clean_env, run_cli  # noqa: E402
from tareqlib import approval as approval_mod, fsutil, lock as lock_mod, txn, workflow  # noqa: E402
from tareqlib.approval import Approval, ApprovalError  # noqa: E402
from tareqlib.sync import SyncError, apply_plan  # noqa: E402
from test_manager import Env, git, snapshot, txn_pending  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def phrase(fp: str) -> str:
    return approval_mod.confirmation_phrase(fp)


# --------------------------------------------------------------------------- approval (D-26)

class CliEnv(Env):
    """Env plus helpers to drive bin/tareq the way a person or an unattended caller would."""

    def setUp(self):
        super().setUp()
        self.env = clean_env(TAREQ_CACHE=os.environ["TAREQ_CACHE"])

    def sync_args(self, *extra):
        return ["sync", "--project", self.proj, "--library", self.lib, "--commit", self.commit, *extra]

    def cli_plan(self):
        r = run_cli(self.sync_args(), ctty=False, env=self.env)
        self.assertEqual(r.code, 0, r.stderr)
        return next(line.split(": ")[1] for line in r.stdout.splitlines() if line.startswith("Plan fingerprint"))


class TestApprovalEnforcement(CliEnv):
    def test_no_controlling_terminal_fails_closed(self):
        fp = self.cli_plan()
        before = snapshot(self.proj)
        r = run_cli(self.sync_args("--apply", fp), ctty=False, env=self.env)
        self.assertEqual(r.code, 2, r.stdout + r.stderr)
        self.assertIn("no controlling terminal", r.stderr)
        self.assertEqual(snapshot(self.proj), before)

    def test_piped_confirmation_is_not_approval(self):
        fp = self.cli_plan()
        before = snapshot(self.proj)
        r = run_cli(self.sync_args("--apply", fp), ctty=False, env=self.env,
                    stdin_data=(phrase(fp) + "\n") * 5)
        self.assertEqual(r.code, 2)
        self.assertEqual(snapshot(self.proj), before)

    def test_agent_harness_marker_refuses_even_with_a_terminal(self):
        fp = self.cli_plan()
        before = snapshot(self.proj)
        env = {**self.env, "CLAUDECODE": "1"}
        r = run_cli(self.sync_args("--apply", fp), answers=[phrase(fp)], env=env)
        self.assertEqual(r.code, 2, r.stdout + r.stderr)
        self.assertIn("agent harness", r.stderr)
        self.assertEqual(snapshot(self.proj), before)

    def test_wrong_confirmation_is_denied(self):
        fp = self.cli_plan()
        before = snapshot(self.proj)
        for answer in ("yes", "y", "apply", phrase("sha256:" + "0" * 64), phrase(fp) + " now", ""):
            with self.subTest(answer=answer):
                r = run_cli(self.sync_args("--apply", fp), answers=[answer], env=self.env)
                self.assertEqual(r.code, 2, r.tty)
                self.assertEqual(snapshot(self.proj), before)

    def test_correct_confirmation_applies_and_records_the_approval(self):
        fp = self.cli_plan()
        r = run_cli(self.sync_args("--apply", fp), answers=[phrase(fp)], env=self.env)
        self.assertEqual(r.code, 0, r.stderr + r.tty)
        lock = v.load_yaml(self.proj / ".tareq/skills.lock")
        self.assertEqual(lock["approval"]["channel"], "tty")
        self.assertTrue(lock["approval"]["approver"])
        self.assertEqual(lock["plan_fingerprint"], fp)
        self.assertIn("Approved by:", (self.proj / ".tareq/history.md").read_text())
        # the confirmation prompt and phrase live on the terminal only, never on stdout/stderr
        for stream in (r.stdout, r.stderr):
            self.assertNotIn(phrase(fp), stream)
            self.assertNotIn("approval required", stream)
        self.assertIn(phrase(fp), r.tty)

    def test_fingerprint_alone_is_never_approval(self):
        fp = self.plan().fingerprint
        for bogus in (fp, Approval(fp, "script", "agent", "2026-10-30T00:00:00Z"), None, "yes"):
            with self.subTest(bogus=str(bogus)[:30]):
                with self.assertRaises(ApprovalError):
                    approval_mod.require(bogus, fp)
        with self.assertRaises(ApprovalError):
            workflow.apply_project_sync(self.proj, fp, commit=self.commit,  # a bare string
                                        source=str(self.lib), home=self.home)
        self.assertFalse((self.proj / ".tareq/skills.lock").exists())

    def test_stale_fingerprint_rejected_before_any_prompt(self):
        r = run_cli(self.sync_args("--apply", "sha256:" + "0" * 64), answers=["x"], env=self.env)
        self.assertEqual(r.code, 1)
        self.assertNotIn("approval required", r.tty)

    def test_destination_change_while_prompt_is_open_invalidates_approval(self):
        fp = self.cli_plan()
        before = snapshot(self.proj)

        def tamper():
            (self.proj / "opencode.json").write_text(json.dumps({"theme": "dark"}))
        r = run_cli(self.sync_args("--apply", fp), answers=[phrase(fp)], before_answer=tamper, env=self.env)
        self.assertEqual(r.code, 2, r.stderr)
        self.assertIn("approval does not match", r.stderr)
        self.assertFalse((self.proj / ".tareq/skills.lock").exists())
        after = snapshot(self.proj)
        after.pop("opencode.json")
        self.assertEqual(after, before)

    def test_config_change_while_prompt_is_open_invalidates_approval(self):
        fp = self.cli_plan()
        r = run_cli(self.sync_args("--apply", fp), answers=[phrase(fp)], env=self.env,
                    before_answer=lambda: self.edit_config(lambda d: d["include"].append("demo-pentest")))
        self.assertEqual(r.code, 2, r.stderr)
        self.assertFalse((self.proj / ".tareq/skills.lock").exists())

    def test_history_or_lock_change_invalidates_approval_even_if_operations_are_unchanged(self):
        """The destination component of the fingerprint: operations stay identical (append
        history, write lock) but the state they will build on changed."""
        self.sync()
        fp = self.plan().fingerprint
        history = self.proj / ".tareq/history.md"
        history.write_text(history.read_text() + "\nowner wrote this by hand\n")
        replanned = self.plan()
        self.assertEqual([o["op"] for o in replanned.operations], ["write_lock", "append_history"])
        self.assertNotEqual(replanned.fingerprint, fp)
        before = snapshot(self.proj)
        with self.assertRaises(ApprovalError):
            workflow.apply_project_sync(self.proj, self.approval_for(fp), commit=self.commit,
                                        source=str(self.lib), home=self.home)
        self.assertEqual(snapshot(self.proj), before)

    def test_destination_changed_between_plan_and_write_is_refused(self):
        plan = self.plan()                                   # approved plan object, not re-planned
        (self.proj / "opencode.json").write_text(json.dumps({"theme": "dark"}))
        before = snapshot(self.proj)
        with self.assertRaises(SyncError) as ctx:
            self.apply_locked(plan)
        self.assertIn("changed after planning", str(ctx.exception))
        self.assertEqual(snapshot(self.proj), before)
        self.assertFalse(txn_pending(self.proj))

    def test_rollback_apply_needs_a_terminal_and_confirmation(self):
        self.sync()
        rev1 = self.proj_commit("sync 1")
        self.edit_config(lambda d: d["include"].append("demo-pentest"))
        self.sync()
        self.proj_commit("sync 2")
        base = ["rollback", "--project", self.proj, "--library", self.lib, "--to", rev1]
        plan = run_cli(base, ctty=False, env=self.env)
        self.assertEqual(plan.code, 0, plan.stderr)
        fp = next(line.split(": ")[1] for line in plan.stdout.splitlines() if line.startswith("Plan fingerprint"))
        before = snapshot(self.proj)
        refused = run_cli(base + ["--apply", fp], ctty=False, env=self.env)
        self.assertEqual(refused.code, 2)
        self.assertEqual(snapshot(self.proj), before)
        ok = run_cli(base + ["--apply", fp], answers=[phrase(fp)], env=self.env)
        self.assertEqual(ok.code, 0, ok.stderr + ok.tty)
        self.assertFalse((self.proj / ".claude/skills/demo-pentest").exists())

    def test_no_flag_or_environment_variable_skips_approval(self):
        fp = self.cli_plan()
        before = snapshot(self.proj)
        for flag in ("--yes", "--force", "--approve", "--no-confirm", "--assume-yes", "--home"):
            with self.subTest(flag=flag):
                r = run_cli(self.sync_args("--apply", fp, flag, str(self.tmp)), ctty=False, env=self.env)
                self.assertNotEqual(r.code, 0)
                self.assertIn("unrecognized arguments", r.stderr)
        env = {**self.env, "TAREQ_YES": "1", "TAREQ_ASSUME_YES": "1", "TAREQ_APPROVE": fp, "CI": "1"}
        r = run_cli(self.sync_args("--apply", fp), ctty=False, env=env)
        self.assertEqual(r.code, 2)
        self.assertEqual(snapshot(self.proj), before)


class TestApprovalPrompt(unittest.TestCase):
    """request_tty_approval against a pseudo-terminal we control (tty_path seam, not CLI)."""

    def setUp(self):
        import pty
        self.master, self.slave = pty.openpty()
        self.path = os.ttyname(self.slave)
        self.addCleanup(self._close)

    def _close(self):
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def request(self, **kw):
        return approval_mod.request_tty_approval(
            summary=kw.pop("summary", "summary"), fingerprint="sha256:" + "ab" * 32, action="test",
            tty_path=self.path, environ={}, **kw)

    def test_timeout_is_a_denial(self):
        with self.assertRaises(approval_mod.ApprovalDenied) as ctx:
            self.request(timeout=0.3)
        self.assertIn("timed out", str(ctx.exception))

    def test_hangup_is_a_denial_not_a_crash(self):
        def hang_up():
            time.sleep(0.4)
            os.close(self.master)   # the terminal goes away while the prompt is waiting
        t = threading.Thread(target=hang_up)
        t.start()
        try:
            with self.assertRaises(approval_mod.ApprovalDenied):
                self.request(timeout=5)
        finally:
            t.join()

    def test_terminal_io_error_is_a_denial_not_a_crash(self):
        import errno
        for failing in ("write", "read"):
            with self.subTest(failing=failing):
                os.write(self.master, b"x\n")   # a complete line so the read path is reached
                real = getattr(os, failing)
                calls = {"n": 0}

                def flaky(fd, *args, _real=real, _calls=calls):
                    _calls["n"] += 1
                    if _calls["n"] == 1 or failing == "write":
                        raise OSError(errno.EIO, "Input/output error")
                    return _real(fd, *args)
                with mock.patch(f"os.{failing}", flaky), self.assertRaises(approval_mod.ApprovalDenied) as ctx:
                    self.request(timeout=2)
                self.assertIn("terminal error", str(ctx.exception))

    def test_correct_phrase_typed_on_the_terminal_is_accepted(self):
        os.write(self.master, (approval_mod.confirmation_phrase("sha256:" + "ab" * 32) + "\n").encode())
        got = self.request(timeout=5)
        self.assertEqual((got.channel, got.fingerprint), ("tty", "sha256:" + "ab" * 32))

    def test_summary_cannot_inject_terminal_control_sequences(self):
        evil = "ok\x1b[2J\x1b[31mFAKE: type nothing\x1b[0m\rapply 000000000000\x07\x9b"
        with self.assertRaises(approval_mod.ApprovalDenied):
            self.request(summary=evil, timeout=0.3)
        shown = os.read(self.master, 65536).decode(errors="replace")
        for bad in ("\x1b", "\x07", "\x9b"):
            self.assertNotIn(bad, shown)
        self.assertIn("FAKE: type nothing", shown)   # text is kept, only control bytes are removed

    def test_recover_on_a_non_tareq_directory_creates_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(workflow.recover_project(Path(d)))
            self.assertEqual(list(Path(d).iterdir()), [])


class TestNoAlternatePaths(CliEnv):
    def test_only_approval_gated_cli_functions_reach_apply(self):
        tree = ast.parse((ROOT / "bin/tareqlib/cli.py").read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            calls = {c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "")
                     for c in ast.walk(fn) if isinstance(c, ast.Call)}
            if calls & {"apply_project_sync", "apply_rollback", "apply_plan"}:
                self.assertIn("_approve", calls, f"cli.{fn.name} applies without _approve()")

    def test_apply_plan_is_only_called_from_the_locked_workflow_functions(self):
        allowed = {("workflow.py", "apply_project_sync"), ("workflow.py", "apply_rollback")}
        for path in sorted((ROOT / "bin").rglob("*.py")):
            tree = ast.parse(path.read_text())
            for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
                for c in ast.walk(fn):
                    if isinstance(c, ast.Call) and getattr(c.func, "id", getattr(c.func, "attr", "")) == "apply_plan":
                        if fn.name != "apply_plan":
                            self.assertIn((path.name, fn.name), allowed, f"{path.name}:{fn.name}")

    def test_every_subcommand_writes_only_what_it_documents(self):
        self.sync()
        self.proj_commit("synced")
        base = ["--project", self.proj]
        cases = {
            "scan": (["scan", *base], set()),
            "select": (["select", *base], set()),
            "sync plan": (self.sync_args(), set()),
            "rollback plan": (["rollback", *base, "--library", self.lib, "--to", "HEAD"], set()),
            "doctor": (["doctor", *base], set()),
            "recover (nothing pending)": (["recover", *base], set()),
            "note": (["note", *base, "--category", "lessons", "hello"], {".tareq/history.md"}),
        }
        for name, (args, may_change) in cases.items():
            with self.subTest(cmd=name):
                before = snapshot(self.proj)
                run_cli(args, ctty=False, env=self.env)
                after = snapshot(self.proj)
                changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
                self.assertLessEqual(changed, may_change)
        before = snapshot(self.proj)  # select --init on a project that has no config creates only it
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        run_cli(["select", "--project", fresh, "--init", "--repo", "https://example.com/x", "--ref", "main"],
                ctty=False, env=self.env)
        self.assertEqual(set(snapshot(fresh)) - {".tareq/", ".tareq/.lock"}, {".tareq/skills.yaml"})
        self.assertEqual(snapshot(self.proj), before)


# --------------------------------------------------------------------------- F1 locking

class TestProjectLock(Env):
    def _holder(self, seconds=30):
        code = ("import sys, time; sys.path.insert(0, %r)\nfrom pathlib import Path\n"
                "from tareqlib.lock import project_lock\n"
                "with project_lock(Path(%r)):\n    print('locked', flush=True); time.sleep(%s)\n"
                % (str(ROOT / "bin"), str(self.proj), seconds))
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.stdout.readline().strip(), "locked")
        return proc

    def test_mutating_operations_are_refused_while_another_process_holds_the_lock(self):
        plan = self.plan()
        holder = self._holder()
        try:
            before = snapshot(self.proj)
            ops = {
                "sync": lambda: workflow.apply_project_sync(
                    self.proj, self.approval_for(plan.fingerprint), commit=self.commit,
                    source=str(self.lib), home=self.home),
                "note": lambda: workflow.add_note(self.proj, "lessons", "x"),
                "recover": lambda: workflow.recover_project(self.proj),
                "init": lambda: workflow.init_config(self.proj, "x"),
            }
            for name, op in ops.items():
                with self.subTest(op=name), self.assertRaises(lock_mod.ProjectBusy):
                    op()
            self.assertEqual(snapshot(self.proj), before)
        finally:
            holder.kill()
            holder.wait()
        self.sync()  # the lock died with its holder

    def test_lock_is_released_when_the_holder_is_killed(self):
        holder = self._holder()
        holder.kill()
        holder.wait()
        with lock_mod.project_lock(self.proj):
            pass

    def test_concurrent_apply_and_note_cannot_lose_or_corrupt_state(self):
        plan = self.plan()
        entered, release = threading.Event(), threading.Event()
        outcome = {}

        def hook(step):
            if step == "op:0:before":
                entered.set()
                release.wait(20)

        def run():
            outcome["lock"] = workflow.apply_project_sync(
                self.proj, self.approval_for(plan.fingerprint), commit=self.commit,
                source=str(self.lib), home=self.home, fault_hook=hook)
        t = threading.Thread(target=run)
        t.start()
        self.assertTrue(entered.wait(20))
        with self.assertRaises(lock_mod.ProjectBusy):
            workflow.add_note(self.proj, "lessons", "racing note")
        with self.assertRaises(lock_mod.ProjectBusy):
            workflow.apply_project_sync(self.proj, self.approval_for(plan.fingerprint),
                                        commit=self.commit, source=str(self.lib), home=self.home)
        release.set()
        t.join(30)
        self.assertEqual(sorted(s["id"] for s in outcome["lock"]["skills"]),
                         ["demo-project-review", "demo-spring-guide", "demo-testing-base"])
        self.assertEqual({i.code for i in workflow.doctor(self.proj, home=self.home) if i.severity == "error"}, set())
        self.assertNotIn("racing note", (self.proj / ".tareq/history.md").read_text())

    def test_apply_plan_refuses_to_run_without_the_project_lock(self):
        plan = self.plan()
        before = snapshot(self.proj)
        with self.assertRaises(RuntimeError):
            apply_plan(self.proj, plan, self.approval_for(plan.fingerprint))
        self.assertEqual(snapshot(self.proj), before)

    def test_lock_file_and_directory_must_not_be_symlinks(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (self.proj / ".tareq/.lock").symlink_to(outside / "lockfile")
        with self.assertRaises(fsutil.UnsafePathError), lock_mod.project_lock(self.proj):
            pass
        self.assertEqual(list(outside.iterdir()), [])
        (self.proj / ".tareq/.lock").unlink()
        moved = self.tmp / "moved-tareq"
        (self.proj / ".tareq").rename(moved)
        (self.proj / ".tareq").symlink_to(moved)
        with self.assertRaises(fsutil.UnsafePathError), lock_mod.project_lock(self.proj):
            pass


# --------------------------------------------------------------------------- F2 journal + crash

KILL_SCRIPT = """
import os, signal, sys
sys.path[:0] = [{bin!r}]
os.environ['TAREQ_CACHE'] = {cache!r}
from pathlib import Path
from tareqlib import approval, workflow
approval.ACCEPTED_CHANNELS = frozenset({{'tty', 'test-harness'}})
count = {{'n': -1}}
def hook(step):
    count['n'] += 1
    if count['n'] == {kill_at}:
        os.kill(os.getpid(), signal.SIGKILL)
workflow.{call}
"""


class TestCrashRecovery(Env):
    def setUp(self):
        super().setUp()
        (self.proj / "CLAUDE.md").write_text("owner rules\n")
        manual = self.proj / ".claude/skills/my-own-skill"
        manual.mkdir(parents=True)
        (manual / "SKILL.md").write_text("---\nname: my-own-skill\ndescription: mine\n---\n")
        self.sync()                                   # state A (has deletes + settings next time)
        self.edit_config(lambda d: d.update(packs=["core"], include=["demo-project-review", "demo-pentest"]))
        self.plan2 = self.plan()                      # state A -> B
        self.assertTrue(self.plan2.ok, self.plan2.summary)
        self.pre = snapshot(self.proj)
        self.steps = self._record_steps()

    def _record_steps(self):
        probe = self.tmp / "probe"
        shutil.copytree(self.proj, probe)
        steps: list[str] = []
        with lock_mod.project_lock(probe):
            plan, ctx = workflow.plan_project_sync(probe, source=str(self.lib), commit=self.commit, home=self.home)
            apply_plan(probe, plan, self.approval_for(plan.fingerprint), fault_hook=steps.append)
        shutil.rmtree(probe)
        return steps

    def kill_apply(self, project: Path, kill_at: int) -> int:
        call = ("apply_project_sync(Path(%r), approval.Approval(%r, 'test-harness', 'tester', "
                "'2026-10-30T00:00:00Z'), commit=%r, source=%r, home=Path(%r), fault_hook=hook)"
                % (str(project), self.plan2.fingerprint, self.commit, str(self.lib), str(self.home)))
        script = KILL_SCRIPT.format(bin=str(ROOT / "bin"), cache=os.environ["TAREQ_CACHE"], kill_at=kill_at, call=call)
        return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120).returncode

    def clone(self, name: str) -> Path:
        dest = self.tmp / name
        shutil.copytree(self.proj, dest, symlinks=True)
        return dest

    def test_steps_cover_journal_every_operation_and_commit(self):
        names = set(self.steps)
        for expected in ("txn:begin", "txn:prepared", "verify:before", "commit:before", "commit:marker",
                         "commit:cleaned", "write:tmp", "write:replaced"):
            self.assertIn(expected, names)
        self.assertTrue(any(s.startswith("txn:backup:") for s in self.steps))
        ops = [s for s in self.steps if s.startswith("op:") and s.endswith(":before")]
        self.assertEqual(len(ops), len(self.plan2.operations))

    def test_sigkill_at_every_step_recovers_to_pre_state_or_completed_state(self):
        marker = self.steps.index("commit:marker")
        for index, name in enumerate(self.steps):
            with self.subTest(step=name, index=index):
                victim = self.clone(f"victim-{index}")
                self.assertEqual(self.kill_apply(victim, index), -signal.SIGKILL)
                result = workflow.recover_project(victim)
                self.assertFalse(txn_pending(victim))
                self.assertEqual([p for p in victim.rglob(".tareq-tmp-*")], [])
                if index < marker:
                    self.assertEqual(snapshot(victim), self.pre, f"not restored after kill at {name}")
                    self.assertIn(result, (None, "discarded", "rolled-back"))
                else:
                    self.assertIn(result, (None, "committed"))
                    errors = [i for i in workflow.doctor(victim, home=self.home) if i.severity == "error"]
                    self.assertEqual(errors, [], [str(e) for e in errors])
                    lock = v.load_yaml(victim / ".tareq/skills.lock")
                    self.assertEqual(sorted(s["id"] for s in lock["skills"]),
                                     ["demo-pentest", "demo-project-review", "demo-testing-base"])
                    self.assertEqual((victim / "CLAUDE.md").read_text(), "owner rules\n")
                    self.assertTrue((victim / ".claude/skills/my-own-skill/SKILL.md").is_file())
                shutil.rmtree(victim)

    def test_crash_before_the_journal_is_durable_leaves_the_project_untouched(self):
        prepared = self.steps.index("txn:prepared")
        for index in range(0, prepared):
            with self.subTest(index=index):
                victim = self.clone(f"early-{index}")
                self.assertEqual(self.kill_apply(victim, index), -signal.SIGKILL)
                # step 0 (txn:begin) is before anything exists on disk; later steps leave a partial dir
                self.assertEqual(workflow.recover_project(victim), None if index == 0 else "discarded")
                self.assertEqual(snapshot(victim), self.pre)
                shutil.rmtree(victim)

    def test_reapplying_after_recovery_succeeds(self):
        for index in (self.steps.index("op:2:before"), self.steps.index("verify:before")):
            with self.subTest(index=index):
                victim = self.clone(f"again-{index}")
                self.assertEqual(self.kill_apply(victim, index), -signal.SIGKILL)
                workflow.recover_project(victim)
                workflow.apply_project_sync(victim, self.approval_for(self.plan2.fingerprint),
                                            commit=self.commit, source=str(self.lib), home=self.home)
                errors = [i for i in workflow.doctor(victim, home=self.home) if i.severity == "error"]
                self.assertEqual(errors, [])
                shutil.rmtree(victim)

    def test_crash_during_recovery_is_repaired_by_running_recovery_again(self):
        crashed = self.clone("crashed")
        self.assertEqual(self.kill_apply(crashed, self.steps.index("op:3:after")), -signal.SIGKILL)
        probe = self.tmp / "recovery-probe"
        shutil.copytree(crashed, probe, symlinks=True)
        recorded: list[str] = []
        workflow.recover_project(probe, hook=recorded.append)
        self.assertGreater(len(recorded), 3, recorded)
        for index, name in enumerate(recorded):
            with self.subTest(recovery_step=name):
                victim = self.tmp / f"recovering-{index}"
                shutil.copytree(crashed, victim, symlinks=True)
                script = KILL_SCRIPT.format(
                    bin=str(ROOT / "bin"), cache=os.environ["TAREQ_CACHE"], kill_at=index,
                    call="recover_project(Path(%r), hook=hook)" % str(victim))
                rc = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=120).returncode
                self.assertEqual(rc, -signal.SIGKILL)
                workflow.recover_project(victim)
                self.assertEqual(snapshot(victim), self.pre)
                shutil.rmtree(victim)

    def test_note_and_next_plan_never_build_on_a_half_applied_state(self):
        victim = self.clone("note-victim")
        self.assertEqual(self.kill_apply(victim, self.steps.index("verify:before")), -signal.SIGKILL)
        self.assertTrue(txn_pending(victim))
        blocked, _ = workflow.plan_project_sync(victim, source=str(self.lib), commit=self.commit, home=self.home)
        self.assertFalse(blocked.ok)
        self.assertTrue(any("tareq recover" in b for b in blocked.blocks), blocked.blocks)
        self.assertIn("txn-pending", {i.code for i in workflow.doctor(victim, home=self.home)})
        workflow.add_note(victim, "lessons", "kept after crash")   # recovers first, then appends
        self.assertFalse(txn_pending(victim))
        text = (victim / ".tareq/history.md").read_text()
        self.assertIn("kept after crash", text)
        before = (self.proj / ".tareq/history.md").read_text()      # the pre-sync history
        self.assertEqual(text.count("\n## "), before.count("\n## ") + 1)   # only the note was added

    def test_corrupt_or_malicious_journal_leaves_the_project_untouched(self):
        crashed = self.clone("journal-victim")
        self.assertEqual(self.kill_apply(crashed, self.steps.index("op:3:after")), -signal.SIGKILL)
        first = json.loads((crashed / ".tareq/.txn/journal.json").read_text())["entries"][0]["path"]

        def retarget(path):
            return lambda journal, backup: journal.write_text(journal.read_text().replace(first, path))
        cases = {
            "corrupt backup": lambda journal, backup: backup.write_text("tampered"),
            "owner file path": retarget("CLAUDE.md"),
            "path traversal": retarget("../outside"),
            "garbage": lambda journal, backup: journal.write_text("{not json"),
        }
        for name, tamper in cases.items():
            with self.subTest(case=name):
                victim = self.tmp / ("tampered-" + name.replace(" ", "-"))
                shutil.copytree(crashed, victim, symlinks=True)
                tamper(victim / ".tareq/.txn/journal.json", victim / ".tareq/.txn/files" / first)
                before = snapshot(victim)
                with self.assertRaises(txn.TransactionError):
                    workflow.recover_project(victim)
                self.assertEqual(snapshot(victim), before)
                self.assertEqual((victim / "CLAUDE.md").read_text(), "owner rules\n")

    def test_forged_journal_with_its_own_backup_cannot_write_owner_or_outside_files(self):
        """A planted journal that ships a matching backup must not turn recovery into a
        file-overwrite primitive: only tareq-owned paths are ever accepted."""
        crashed = self.clone("forged-journal")
        self.assertEqual(self.kill_apply(crashed, self.steps.index("op:3:after")), -signal.SIGKILL)
        txn_dir = crashed / ".tareq/.txn"
        journal = json.loads((txn_dir / "journal.json").read_text())
        for forged in ("CLAUDE.md", ".claude/settings.local.json", "../escaped.txt"):
            with self.subTest(path=forged):
                victim = self.tmp / ("forged-" + forged.replace("/", "_").replace(".", "_"))
                shutil.copytree(crashed, victim, symlinks=True)
                evil = b"attacker content\n"
                backup = victim / ".tareq/.txn/files" / forged
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(evil)
                planted = dict(journal)
                planted["entries"] = journal["entries"] + [
                    {"path": forged, "before": fsutil.sha256_bytes(evil), "backup": True, "mode": 0o644}]
                (victim / ".tareq/.txn/journal.json").write_text(json.dumps(planted))
                before = snapshot(victim)
                with self.assertRaises(txn.TransactionError):
                    workflow.recover_project(victim)
                self.assertEqual(snapshot(victim), before)
                self.assertEqual((victim / "CLAUDE.md").read_text(), "owner rules\n")
                self.assertFalse((victim.parent / "escaped.txt").exists())

    def test_writes_are_fsynced_files_and_directories(self):
        import stat
        calls = {"file": 0, "dir": 0}
        real_fsync = os.fsync

        def counting_fsync(fd):
            kind = "dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
            calls[kind] += 1
            return real_fsync(fd)
        with mock.patch("os.fsync", counting_fsync):
            self.sync()
        writes = len([o for o in self.plan2.operations if o["op"] in ("write", "write_lock", "append_history")])
        self.assertGreaterEqual(calls["file"], writes)       # every written file, plus the backups
        self.assertGreaterEqual(calls["dir"], writes)        # and its directory entry


# --------------------------------------------------------------------------- F4 ownership

class TestOwnershipForgery(Env):
    def setUp(self):
        super().setUp()
        self.manual = self.proj / ".claude/skills/my-own-skill"
        self.manual.mkdir(parents=True)
        (self.manual / "SKILL.md").write_text("---\nname: my-own-skill\ndescription: mine\n---\nmine\n")
        (self.proj / "CLAUDE.md").write_text("owner rules\n")
        (self.proj / ".claude/settings.json").write_text(json.dumps({"permissions": {"deny": ["Bash(rm *)"]}}))
        self.edit_config(lambda d: d["include"].append("demo-pentest"))
        self.sync()
        self.lock_path = self.proj / ".tareq/skills.lock"
        self.keep = {k: h for k, h in snapshot(self.proj).items() if k in (
            "CLAUDE.md", ".claude/skills/my-own-skill/SKILL.md")}

    def forge(self, fn):
        lock = v.load_yaml(self.lock_path)
        fn(lock)
        self.lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))

    def assertForgedAndHarmless(self, fragment="never", code="ownership-forged"):
        plan = self.plan()
        self.assertFalse(plan.ok, plan.summary)
        self.assertTrue(any(fragment in b for b in plan.blocks), plan.blocks)
        self.assertFalse(any(o["op"] == "delete" for o in plan.operations))
        validator = {i.code for i in v.validate(self.lib / "catalog", self.proj) if i.severity == "error"}
        self.assertIn(code, validator)
        self.assertIn("lock-invalid", {i.code for i in workflow.doctor(self.proj, home=self.home)})
        now = snapshot(self.proj)
        for k, h in self.keep.items():
            self.assertEqual(now[k], h)
        self.assertEqual(json.loads((self.proj / ".claude/settings.json").read_text())["permissions"],
                         {"deny": ["Bash(rm *)"]})

    def test_claiming_an_owner_file_is_rejected(self):
        self.forge(lambda l: l["generated"].append(
            {"path": "CLAUDE.md", "hash": fsutil.sha256_file(self.proj / "CLAUDE.md")}))
        self.assertForgedAndHarmless()

    def test_claiming_a_manual_skill_directory_is_rejected(self):
        self.forge(lambda l: l["generated"].append(
            {"path": ".claude/skills/my-own-skill/SKILL.md",
             "hash": fsutil.sha256_file(self.manual / "SKILL.md")}))
        self.assertForgedAndHarmless("not registered")

    def test_registering_and_claiming_a_manual_skill_fails_library_corroboration(self):
        def forge(lock):
            data = (self.manual / "SKILL.md").read_bytes()
            h = fsutil.sha256_bytes(data)
            lock["skills"].append({"id": "my-own-skill", "version": "1", "source": {"type": "local"},
                                   "content_hash": h, "license": None, "via": ["include"],
                                   "output_hash": v.mapping_hash_of({"SKILL.md": h})})
            lock["generated"].append({"path": ".claude/skills/my-own-skill/SKILL.md", "hash": h})
        self.forge(forge)
        plan = self.plan()
        self.assertFalse(plan.ok, plan.summary)
        self.assertTrue(any("not corroborated" in b for b in plan.blocks), plan.blocks)
        self.assertFalse(any(o["op"] == "delete" for o in plan.operations))
        now = snapshot(self.proj)
        for k, h in self.keep.items():
            self.assertEqual(now[k], h)

    def test_claiming_a_user_setting_is_rejected(self):
        def forge(lock):
            entry = next(s for s in lock["settings"] if s["file"] == ".claude/settings.json")
            entry["keys"].append({"key": ["permissions", "deny"], "value": ["Bash(rm *)"]})
        self.forge(forge)
        self.assertForgedAndHarmless("never sets")

    def test_claiming_an_unregistered_or_wrongly_valued_override_is_rejected(self):
        for key, value in ((["skillOverrides", "my-own-skill"], "user-invocable-only"),
                           (["skillOverrides", "demo-pentest"], "off")):
            with self.subTest(key=key, value=value):
                def forge(lock, key=key, value=value):
                    entry = next(s for s in lock["settings"] if s["file"] == ".claude/settings.json")
                    entry["keys"].append({"key": key, "value": value})
                lock_before = self.lock_path.read_text()
                self.forge(forge)
                self.assertForgedAndHarmless("never sets")
                self.lock_path.write_text(lock_before)

    def test_inconsistent_output_hash_is_rejected(self):
        self.forge(lambda l: l["skills"][0].update(output_hash="sha256:" + "a" * 64))
        self.assertForgedAndHarmless("output_hash", code="ownership-inconsistent")

    def test_path_allowlist_table(self):
        good = [".claude/skills/demo-a/SKILL.md", ".claude/skills/demo-a/sub/dir/file.md",
                ".claude/rules/tareq-skills.md", ".tareq/SKILLS-backend.md", ".tareq/.gitignore"]
        bad = ["CLAUDE.md", "AGENTS.md", ".claude/settings.json", ".claude/skills/Demo/SKILL.md",
               ".claude/skills/demo-a/../../CLAUDE.md", ".claude/skills//SKILL.md", "/etc/passwd",
               ".claude/skills/demo-a/", ".claude/skills/demo-a", ".claude\\skills\\x\\SKILL.md",
               ".tareq/skills.yaml", ".tareq/history.md", ".tareq/SKILLS-Backend.md",
               ".claude/rules/other.md", "./.claude/skills/demo-a/SKILL.md", ".claude/skills/demo-а/SKILL.md", ""]
        for p in good:
            self.assertTrue(v.is_generated_path(p), p)
        for p in bad:
            self.assertFalse(v.is_generated_path(p), p)
        self.assertTrue(v.is_touchable_path(".tareq/skills.lock"))
        self.assertTrue(v.is_touchable_path("opencode.json"))
        self.assertFalse(v.is_touchable_path("CLAUDE.md"))
        self.assertFalse(v.is_touchable_path(".tareq/skills.yaml"))

    def _fresh_synced_project(self, name):
        fresh = self.tmp / name
        (fresh / ".tareq").mkdir(parents=True)
        shutil.copy(FIX / "project/.tareq/skills.yaml", fresh / ".tareq/skills.yaml")
        git(fresh, "init", "-q")
        self.proj = fresh
        self.edit_config(lambda d: d["include"].append("demo-pentest"))
        self.sync()
        return fresh

    def test_settings_file_created_by_us_is_deleted_only_if_untouched(self):
        orig = self.proj
        try:
            untouched = self._fresh_synced_project("untouched")
            self.assertTrue((untouched / "opencode.json").exists())
            self.edit_config(lambda d: d.update(targets=["claude-code"]))
            self.sync()
            self.assertFalse((untouched / "opencode.json").exists())     # ours and unchanged: removed

            edited = self._fresh_synced_project("edited")
            data = json.loads((edited / "opencode.json").read_text())
            (edited / "opencode.json").write_text(json.dumps(data, indent=4))   # same content, new bytes
            self.edit_config(lambda d: d.update(targets=["claude-code"]))
            self.sync()
            self.assertTrue((edited / "opencode.json").exists(), "hand-touched settings file was deleted")
            self.assertEqual(json.loads((edited / "opencode.json").read_text()), {})
        finally:
            self.proj = orig

    def test_rollback_target_lock_with_forged_claims_is_refused(self):
        self.proj_commit("good lock")
        self.forge(lambda l: l["generated"].append(
            {"path": "CLAUDE.md", "hash": fsutil.sha256_file(self.proj / "CLAUDE.md")}))
        rev_bad = self.proj_commit("forged lock")
        with self.assertRaises(SyncError) as ctx:
            workflow.plan_rollback(self.proj, rev_bad, source=str(self.lib), home=self.home)
        self.assertIn("forged", str(ctx.exception))
        self.assertEqual((self.proj / "CLAUDE.md").read_text(), "owner rules\n")

    def test_rollback_does_not_trust_a_library_named_by_an_old_lock(self):
        self.proj_commit("good lock")
        lock = v.load_yaml(self.lock_path)
        lock["catalog"]["repo"] = "https://evil.example.com/skills"
        self.lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))
        rev_evil = self.proj_commit("lock naming another library")
        with self.assertRaises(SyncError) as ctx:
            workflow.plan_rollback(self.proj, rev_evil, home=self.home)
        self.assertIn("not the project's configured library", str(ctx.exception))
        plan, _ = workflow.plan_rollback(self.proj, rev_evil, source=str(self.lib), home=self.home)  # explicit opt-in
        self.assertTrue(plan.ok, plan.summary)


# --------------------------------------------------------------------------- F5 symlinks

class TestSymlinkWrites(Env):
    def test_note_refuses_a_symlinked_history_file(self):
        outside = self.tmp / "outside.md"
        outside.write_text("outside\n")
        (self.proj / ".tareq/history.md").symlink_to(outside)
        with self.assertRaises(SyncError):
            workflow.add_note(self.proj, "lessons", "x")
        self.assertEqual(outside.read_text(), "outside\n")

    def test_note_refuses_a_dangling_symlink(self):
        target = self.tmp / "created-by-attack.md"
        (self.proj / ".tareq/history.md").symlink_to(target)
        with self.assertRaises(SyncError):
            workflow.add_note(self.proj, "lessons", "x")
        self.assertFalse(target.exists())

    def test_note_refuses_a_symlinked_tareq_directory(self):
        outside = self.tmp / "outside-dir"
        outside.mkdir()
        (self.proj / ".tareq").rename(self.tmp / "real-tareq")
        (self.proj / ".tareq").symlink_to(outside)
        with self.assertRaises((SyncError, fsutil.UnsafePathError)):
            workflow.add_note(self.proj, "lessons", "x")
        self.assertEqual(list(outside.iterdir()), [])

    def test_note_does_not_block_on_a_fifo(self):
        os.mkfifo(self.proj / ".tareq/history.md")
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("err", self._try_note()), daemon=True)
        t.start()
        t.join(10)
        self.assertFalse(t.is_alive(), "note blocked on a FIFO")
        self.assertIsInstance(result["err"], SyncError)

    def _try_note(self):
        try:
            workflow.add_note(self.proj, "lessons", "x")
        except Exception as exc:  # noqa: BLE001
            return exc

    def test_note_appends_and_never_rewrites_existing_history(self):
        workflow.add_note(self.proj, "lessons", "first")
        before = (self.proj / ".tareq/history.md").read_bytes()
        workflow.add_note(self.proj, "decisions", "second")
        after = (self.proj / ".tareq/history.md").read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertIn(b"second", after[len(before):])

    def test_init_refuses_dangling_and_live_symlinks_and_existing_files(self):
        config = self.proj / ".tareq/skills.yaml"
        config.unlink()
        target = self.tmp / "elsewhere.yaml"
        config.symlink_to(target)
        with self.assertRaises(SyncError):
            workflow.init_config(self.proj, "x: 1\n")
        self.assertFalse(target.exists())
        target.write_text("precious\n")
        with self.assertRaises(SyncError):
            workflow.init_config(self.proj, "x: 1\n")
        self.assertEqual(target.read_text(), "precious\n")
        config.unlink()
        config.write_text("owner config\n")
        with self.assertRaises(SyncError):
            workflow.init_config(self.proj, "x: 1\n")
        self.assertEqual(config.read_text(), "owner config\n")

    def test_cli_select_init_cannot_write_through_a_symlink(self):
        config = self.proj / ".tareq/skills.yaml"
        config.unlink()
        target = self.tmp / "elsewhere.yaml"
        config.symlink_to(target)
        r = run_cli(["select", "--project", self.proj, "--init", "--repo", "https://example.com/x",
                     "--ref", "main"], ctty=False, env=clean_env(TAREQ_CACHE=os.environ["TAREQ_CACHE"]))
        self.assertEqual(r.code, 1)
        self.assertFalse(target.exists())


# --------------------------------------------------------------------------- F3 home / surface

class TestHomeAndSurface(Env):
    def test_home_option_is_not_part_of_the_public_cli(self):
        self.assertNotIn('"--home"', (ROOT / "bin/tareqlib/cli.py").read_text())
        env = clean_env(TAREQ_CACHE=os.environ["TAREQ_CACHE"])
        for cmd in (["sync", "--library", self.lib], ["rollback", "--to", "HEAD"], ["doctor"]):
            with self.subTest(cmd=cmd[0]):
                r = run_cli([*cmd, "--project", self.proj, "--home", self.tmp], ctty=False, env=env)
                self.assertNotEqual(r.code, 0)
                self.assertIn("unrecognized arguments", r.stderr)

    def test_collision_check_ignores_the_home_environment_variable(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp / "fake-home")}):
            import pwd
            self.assertEqual(fsutil.real_home(), Path(pwd.getpwuid(os.getuid()).pw_dir))
            self.assertNotEqual(fsutil.real_home(), self.tmp / "fake-home")

    def test_environment_is_part_of_the_plan_fingerprint(self):
        base = self.plan().fingerprint
        with mock.patch.dict(os.environ, {"OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1"}):
            self.assertNotEqual(self.plan().fingerprint, base)
        (self.home / ".claude/skills/demo-testing-base").mkdir(parents=True)
        blocked = self.plan()
        self.assertFalse(blocked.ok)
        self.assertNotEqual(blocked.fingerprint, base)


if __name__ == "__main__":
    unittest.main()
