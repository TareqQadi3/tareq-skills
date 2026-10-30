"""Behavioral tests for the M3 manager (bin/tareq, bin/tareqlib).

Every test builds an isolated library git repo (from the synthetic fixtures), a client
project git repo, a fake HOME, and a private cache, so nothing outside the temp dir is
read or written. Safeguards R-12..R-20 each have failing-path tests.
Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "tests"))

import validate_catalog as v  # noqa: E402
from tareqlib import approval as approval_mod, library, lock as lock_mod, scan, selection, workflow  # noqa: E402
from tareqlib.approval import Approval, ApprovalError  # noqa: E402
from tareqlib.fsutil import UnsafePathError, glob_to_regex, safe_dest, sha256_file  # noqa: E402
from tareqlib.sync import SyncError, apply_plan  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
GIT_ID = ["-c", "user.email=test@example.com", "-c", "user.name=test"]


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *GIT_ID, *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def txn_pending(project: Path) -> bool:
    return (project / ".tareq/.txn").exists()


def snapshot(root: Path) -> dict[str, str]:
    """Hash of every file (and symlink target) under root, excluding .git."""
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if rel == ".git" or rel.startswith(".git/") or rel == ".tareq/.lock":
            continue  # .tareq/.lock is the (empty) flock file, not project state
        if p.is_symlink():
            out[rel] = "symlink:" + os.readlink(p)
        elif p.is_file():
            out[rel] = sha256_file(p)
        elif p.is_dir():
            out[rel + "/"] = "dir"
    return out


class Env(unittest.TestCase):
    """Temp library repo + project repo + HOME + cache."""

    def setUp(self):
        # Library-level tests use a harness-only channel; the CLI accepts only a real terminal.
        patcher = mock.patch.object(approval_mod, "ACCEPTED_CHANNELS", frozenset({"tty", "test-harness"}))
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._env = dict(os.environ)
        os.environ["TAREQ_CACHE"] = str(self.tmp / "cache")
        for var in ("OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"):
            os.environ.pop(var, None)
        self.lib = self.tmp / "lib"
        shutil.copytree(FIX / "catalog", self.lib / "catalog")
        shutil.copytree(ROOT / "catalog" / "schema", self.lib / "catalog" / "schema")
        shutil.copytree(FIX / "library", self.lib / "library")
        git(self.lib, "init", "-q")
        self.commit = self.lib_commit("library v1")
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.proj = self.tmp / "proj"
        (self.proj / ".tareq").mkdir(parents=True)
        shutil.copy(FIX / "project" / ".tareq" / "skills.yaml", self.proj / ".tareq" / "skills.yaml")
        git(self.proj, "init", "-q")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    # helpers -------------------------------------------------------------
    def lib_commit(self, message: str) -> str:
        git(self.lib, "add", "-A")
        git(self.lib, "commit", "-qm", message)
        return git(self.lib, "rev-parse", "HEAD")

    def edit_lib_yaml(self, rel: str, fn) -> None:
        path = self.lib / rel
        data = yaml.safe_load(path.read_text())
        fn(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    def edit_config(self, fn) -> None:
        path = self.proj / ".tareq" / "skills.yaml"
        data = yaml.safe_load(path.read_text())
        fn(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    def plan(self, commit=None, **kw):
        plan, _ = workflow.plan_project_sync(self.proj, source=str(self.lib),
                                             commit=commit or self.commit, home=self.home, **kw)
        return plan

    def approval_for(self, fingerprint: str) -> Approval:
        return Approval(fingerprint, "test-harness", "tester", "2026-10-30T00:00:00Z")

    def sync(self, commit=None, **kw):
        plan = self.plan(commit, **kw)
        self.assertTrue(plan.ok, plan.summary)
        return workflow.apply_project_sync(self.proj, self.approval_for(plan.fingerprint),
                                           commit=commit or self.commit, source=str(self.lib),
                                           home=self.home, **kw)

    def apply_locked(self, plan, fingerprint=None, **kw):
        """apply_plan with the project lock held, as the workflow functions do."""
        with lock_mod.project_lock(self.proj):
            return apply_plan(self.proj, plan, self.approval_for(fingerprint or plan.fingerprint), **kw)

    def proj_commit(self, message: str) -> str:
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-qm", message)
        return git(self.proj, "rev-parse", "HEAD")

    def lock(self) -> dict:
        return v.load_yaml(self.proj / ".tareq" / "skills.lock")

    def assertBlocked(self, plan, fragment: str):
        self.assertFalse(plan.ok, plan.summary)
        self.assertTrue(any(fragment in b for b in plan.blocks), plan.blocks)


# --------------------------------------------------------------------------- scan / select

class TestScanAndSelect(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name)
        self.cat, _ = v.load_catalog(ROOT / "catalog")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        (self.p / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.p / rel).write_text(text)

    def test_glob_semantics(self):
        rx = glob_to_regex("**/pom.xml")
        self.assertTrue(rx.match("pom.xml"))
        self.assertTrue(rx.match("a/b/pom.xml"))
        self.assertFalse(rx.match("a/pom.xml.bak"))
        self.assertFalse(glob_to_regex("*.md").match("docs/a.md"))

    def test_spring_next_postgres_rtl_detected_with_implications(self):
        self.write("backend/pom.xml", "<project><dependencies><dependency><groupId>org.postgresql"
                   "</groupId><artifactId>postgresql</artifactId></dependency></dependencies>"
                   "<parent><artifactId>spring-boot-starter-parent</artifactId></parent></project>")
        self.write("web/package.json", json.dumps({"dependencies": {"next": "14.0.0", "react": "18"}}))
        self.write("web/app/layout.tsx", '<html lang="ar" dir="rtl">')
        self.write("db/migration/V1__init.sql", "create table x();")
        found = scan.scan(self.p, self.cat.stacks)
        for sid in ("spring-boot", "java", "nextjs", "react", "nodejs", "postgres", "flyway", "rtl-arabic"):
            self.assertIn(sid, found)
        self.assertNotIn("python", found)

    def test_skill_directories_are_not_part_of_the_project(self):
        # A skill that ships its own requirements.txt / package.json must not make the
        # project look like a Python or Next.js project (found while scanning SMMS).
        self.write(".claude/skills/some-skill/requirements.txt", "requests\n")
        self.write(".claude/skills/some-skill/package.json", json.dumps({"dependencies": {"next": "14"}}))
        self.write(".opencode/skills/other/package.json", json.dumps({"dependencies": {"react": "18"}}))
        self.write("backend/pom.xml", "<project><parent><artifactId>spring-boot-starter-parent</artifactId></parent></project>")
        found = scan.scan(self.p, self.cat.stacks)
        self.assertEqual(sorted(found), ["java", "spring-boot"])

    def test_vendored_dirs_ignored(self):
        self.write("node_modules/x/package.json", json.dumps({"dependencies": {"next": "1"}}))
        found = scan.scan(self.p, self.cat.stacks)
        self.assertNotIn("nextjs", found)
        self.assertNotIn("nodejs", found)

    def test_pip_dependency(self):
        self.write("requirements.txt", "Django==5.0\npsycopg[binary]>=3\n")
        cat, _ = v.load_catalog(FIX / "catalog")
        stacks = {"pg": {"id": "pg", "name": "pg", "detect": {"any": [
            {"dependency": {"ecosystem": "pip", "name": "psycopg"}}]}}}
        self.assertIn("pg", scan.scan(self.p, stacks))

    def test_proposal_uses_default_and_stack_packs_never_marketing(self):
        cat, _ = v.load_catalog(FIX / "catalog")
        proposal = selection.propose(cat, {"spring-boot", "java"})
        self.assertEqual(proposal["config"]["packs"], ["backend-java", "core"])
        self.assertNotIn("demo-marketing-copy", proposal["skills"])

    def test_proposal_lists_same_level_conflicts_for_owner(self):
        cat, _ = v.load_catalog(FIX / "catalog")
        a, b = cat.skills["demo-testing-base"], cat.skills["demo-spring-guide"]
        a["conflicts_with"] = ["demo-spring-guide"]
        b["scope"] = "general"
        proposal = selection.propose(cat, {"spring-boot"})
        self.assertEqual(proposal["needs_owner_decision"], [("demo-spring-guide", "demo-testing-base")])

    def test_select_init_never_overwrites(self):
        self.write(".tareq/skills.yaml", "owner: content\n")
        r = subprocess.run([sys.executable, str(ROOT / "bin" / "tareq"), "select", "--project", str(self.p),
                            "--init", "--repo", "https://example.com/x", "--ref", "main"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertEqual((self.p / ".tareq/skills.yaml").read_text(), "owner: content\n")


# --------------------------------------------------------------------------- sync basics

class TestSync(Env):
    def test_sync_generates_verbatim_pinned_copies(self):
        lock = self.sync()
        for sid in ("demo-project-review", "demo-spring-guide", "demo-testing-base"):
            src = self.lib / "library"
            cat_skill = next(s for s in lock["skills"] if s["id"] == sid)
            self.assertEqual(v.content_hash(self.proj / ".claude/skills" / sid), cat_skill["content_hash"])
        self.assertFalse((self.proj / ".claude/skills/demo-ui-review-general").exists())  # D-16 dropped
        written = self.lock()
        self.assertEqual(written["catalog"]["commit"], self.commit)
        self.assertEqual(written["lock_version"], 2)
        issues = v.validate(self.lib / "catalog", self.proj)
        self.assertEqual({i.code for i in issues if i.severity == "error"}, set(), [str(i) for i in issues])
        self.assertIn(".claude/rules/tareq-skills.md",
                      json.loads((self.proj / "opencode.json").read_text())["instructions"])

    def test_resync_is_idempotent(self):
        self.sync()
        before = snapshot(self.proj)
        plan = self.plan()
        self.assertEqual([o["op"] for o in plan.operations], ["write_lock", "append_history"])
        self.assertEqual(plan.fingerprint, self.plan().fingerprint)  # deterministic
        self.assertEqual(snapshot(self.proj), before)

    def test_ref_resolves_to_exact_commit(self):
        git(self.lib, "tag", "catalog-v0.1.0")
        self.assertEqual(library.resolve_commit(str(self.lib), "catalog-v0.1.0"), self.commit)
        plan, ctx = workflow.plan_project_sync(self.proj, source=str(self.lib), home=self.home)
        self.assertEqual(ctx.commit, self.commit)
        self.assertEqual(plan.desired.lock_base["catalog"]["commit"], self.commit)

    def test_checkout_requires_full_commit(self):
        with self.assertRaises(library.LibraryError):
            library.checkout(str(self.lib), self.commit[:12])

    def test_manual_invocation_via_settings_not_skill_md(self):
        self.edit_config(lambda d: d["include"].append("demo-pentest"))
        self.sync()
        md = (self.proj / ".claude/skills/demo-pentest/SKILL.md").read_text()
        self.assertNotIn("disable-model-invocation", md)
        claude = json.loads((self.proj / ".claude/settings.json").read_text())
        self.assertEqual(claude["skillOverrides"]["demo-pentest"], "user-invocable-only")
        oc = json.loads((self.proj / "opencode.json").read_text())
        self.assertEqual(oc["permission"]["skill"]["demo-pentest"], "ask")
        self.assertEqual(self.lock()["budget"]["used"], 3)  # manual skill not counted for Claude

    def test_frontmatter_overlay_recorded_with_output_hash(self):
        (self.lib / "catalog/overlays/demo-testing-base.yaml").write_text(yaml.safe_dump(
            {"schema_version": 1, "skill": "demo-testing-base", "reason": "shorter",
             "set": {"description": "Overlay description."}}))
        commit = self.lib_commit("overlay")
        self.edit_config(lambda d: d.update(include=[], packs=["core"]))
        lock = self.sync(commit)
        entry = lock["skills"][0]
        self.assertNotEqual(entry["output_hash"], entry["content_hash"])
        self.assertIn("overlay_hash", entry)
        fm, _ = v.split_frontmatter((self.proj / ".claude/skills/demo-testing-base/SKILL.md").read_text())
        self.assertEqual(fm["description"], "Overlay description.")
        self.assertEqual(v.content_hash(self.proj / ".claude/skills/demo-testing-base"), entry["output_hash"])

    def test_opencode_description_limit(self):
        (self.lib / "catalog/overlays/demo-testing-base.yaml").write_text(yaml.safe_dump(
            {"schema_version": 1, "skill": "demo-testing-base", "reason": "long",
             "set": {"description": "x" * 1100}}))
        commit = self.lib_commit("long overlay")
        self.edit_config(lambda d: d.update(include=[], packs=["core"]))
        self.assertBlocked(self.plan(commit), "OpenCode needs 1-1024")

    def test_budget_counts_per_agent(self):
        self.edit_config(lambda d: (d["include"].append("demo-pentest"),
                                    d["budget"].update(max_descriptions=3)))
        self.assertBlocked(self.plan(), "OpenCode budget: 4")  # ask-skills stay listed (R-06)
        self.edit_config(lambda d: d.update(targets=["claude-code"]))
        self.assertTrue(self.plan().ok)

    def test_cli_plan_apply_roundtrip_with_human_confirmation(self):
        from ptyutil import run_cli
        base = ["sync", "--project", self.proj, "--library", self.lib]
        env = {**os.environ, "TAREQ_CACHE": os.environ["TAREQ_CACHE"]}
        env.pop("CLAUDECODE", None)
        plan = run_cli(base + ["--commit", self.commit], ctty=False, env=env)
        self.assertEqual(plan.code, 0, plan.stderr)
        fp = next(line.split(": ")[1] for line in plan.stdout.splitlines() if line.startswith("Plan fingerprint"))
        stale = run_cli(base + ["--commit", self.commit, "--apply", "sha256:" + "0" * 64],
                        answers=["x"], env=env)
        self.assertEqual(stale.code, 1)
        self.assertFalse((self.proj / ".tareq/skills.lock").exists())
        ok = run_cli(base + ["--commit", self.commit, "--apply", fp],
                     answers=[approval_mod.confirmation_phrase(fp)], env=env)
        self.assertEqual(ok.code, 0, ok.stderr + ok.tty)
        doc = run_cli(["doctor", "--project", self.proj, "--library", self.lib], ctty=False, env=env)
        self.assertEqual(doc.code, 0, doc.stdout)


# --------------------------------------------------------------------------- R-12 / R-16

class TestOwnership(Env):
    def add_manual_skill(self, name, body="manual\n", declared=None):
        d = self.proj / ".claude/skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {declared or name}\ndescription: manual\n---\n{body}")
        return d

    def test_r12_existing_unmanaged_skill_blocks(self):
        self.add_manual_skill("demo-testing-base", "different content\n")
        before = snapshot(self.proj)
        self.assertBlocked(self.plan(), "not managed by tareq-skills")
        self.assertEqual(snapshot(self.proj), before)

    def test_r12_adopt_only_when_identical(self):
        d = self.proj / ".claude/skills/demo-testing-base"
        shutil.copytree(self.lib / "library/testing/demo-testing-base", d)
        self.assertBlocked(self.plan(), "not managed")
        self.assertTrue(self.plan(adopt={"demo-testing-base"}).ok)
        (d / "SKILL.md").write_text((d / "SKILL.md").read_text() + "edit\n")
        self.assertBlocked(self.plan(adopt={"demo-testing-base"}), "not managed")

    def test_r12_explicit_overwrite_approval(self):
        self.add_manual_skill("demo-testing-base", "different\n")
        (self.proj / ".claude/skills/demo-testing-base/notes.txt").write_text("x")
        plan = self.plan(approve_overwrite={"demo-testing-base"})
        self.assertTrue(plan.ok, plan.summary)
        self.assertIn("OVERWRITE (approved)", plan.summary)
        self.sync(approve_overwrite={"demo-testing-base"})
        self.assertFalse((self.proj / ".claude/skills/demo-testing-base/notes.txt").exists())

    def test_r12_unmanaged_file_inside_generated_skill_blocks(self):
        self.sync()
        (self.proj / ".claude/skills/demo-testing-base/extra.md").write_text("mine")
        self.assertBlocked(self.plan(), "unmanaged file inside skill")

    def test_r12_hand_edited_generated_file_blocks_update(self):
        self.sync()
        f = self.proj / ".claude/rules/tareq-skills.md"
        f.write_text(f.read_text() + "my edit\n")
        self.assertBlocked(self.plan(), "edited by hand")

    def test_r12_settings_preserved_and_unmanaged_key_blocks(self):
        (self.proj / ".claude").mkdir()
        (self.proj / ".claude/settings.json").write_text(json.dumps(
            {"permissions": {"allow": ["Bash(ls)"]}, "skillOverrides": {"my-skill": "off"}}))
        self.edit_config(lambda d: d["include"].append("demo-pentest"))
        self.sync()
        claude = json.loads((self.proj / ".claude/settings.json").read_text())
        self.assertEqual(claude["permissions"], {"allow": ["Bash(ls)"]})
        self.assertEqual(claude["skillOverrides"]["my-skill"], "off")
        self.assertEqual(claude["skillOverrides"]["demo-pentest"], "user-invocable-only")
        # an unmanaged key with the same name blocks
        (self.proj / "opencode.json").write_text(json.dumps({"permission": {"skill": {"demo-pentest": "deny"}}}))
        self.proj_commit("x")
        shutil.rmtree(self.proj / ".tareq")
        (self.proj / ".tareq").mkdir()
        shutil.copy(FIX / "project/.tareq/skills.yaml", self.proj / ".tareq/skills.yaml")
        self.edit_config(lambda d: d["include"].append("demo-pentest"))
        self.assertBlocked(self.plan(), "not managed by tareq-skills")

    def test_r12_invalid_settings_json_blocks(self):
        (self.proj / "opencode.json").write_text("{ // comment\n}")
        self.assertBlocked(self.plan(), "not valid JSON")

    def test_r16_manual_skills_and_files_untouched_by_removal(self):
        manual = self.add_manual_skill("my-own-skill")
        (self.proj / "CLAUDE.md").write_text("project rules\n")
        self.sync()
        keep = {k: h for k, h in snapshot(self.proj).items() if "my-own-skill" in k or k == "CLAUDE.md"}
        self.edit_config(lambda d: d.update(packs=[], include=["demo-project-review"]))
        lock = self.sync()
        self.assertEqual([s["id"] for s in lock["skills"]], ["demo-project-review"])
        self.assertFalse((self.proj / ".claude/skills/demo-spring-guide").exists())
        self.assertTrue(manual.is_dir())
        self.assertEqual({k: h for k, h in snapshot(self.proj).items() if k in keep}, keep)

    def test_r16_disabled_skill_cannot_be_synced_and_stays_in_catalog(self):
        self.edit_config(lambda d: d["include"].append("demo-old-spring"))
        self.assertBlocked(self.plan(), "inactive-skill-selected")
        cat, _ = v.load_catalog(self.lib / "catalog")
        self.assertEqual(cat.skills["demo-old-spring"]["status"], "disabled")

    def test_r16_hand_edited_owned_file_left_when_skill_removed(self):
        self.sync()
        f = self.proj / ".claude/skills/demo-spring-guide/SKILL.md"
        f.write_text(f.read_text() + "local tweak\n")
        self.edit_config(lambda d: d.update(packs=["core"], include=["demo-project-review"]))
        plan = self.plan()
        self.assertTrue(plan.ok, plan.summary)
        self.assertIn("left untouched", plan.summary)
        self.sync()
        self.assertIn("local tweak", f.read_text())
        self.assertNotIn(".claude/skills/demo-spring-guide/SKILL.md",
                         [g["path"] for g in self.lock()["generated"]])

    def test_lock_cannot_claim_owner_files(self):
        (self.proj / "CLAUDE.md").write_text("owner rules\n")
        self.sync()
        lock_path = self.proj / ".tareq/skills.lock"
        lock = v.load_yaml(lock_path)
        lock["generated"].append({"path": "CLAUDE.md", "hash": sha256_file(self.proj / "CLAUDE.md")})
        lock_path.write_text(yaml.safe_dump(lock, sort_keys=False))
        self.assertBlocked(self.plan(), "never generates")
        self.assertTrue((self.proj / "CLAUDE.md").is_file())

    def test_safe_dest_rejects_symlink_escape(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (self.proj / ".claude").symlink_to(outside)
        with self.assertRaises(UnsafePathError):
            safe_dest(self.proj, ".claude/skills/x/SKILL.md")
        self.assertBlocked(self.plan(), "symlink")
        self.assertEqual(list(outside.iterdir()), [])


# --------------------------------------------------------------------------- R-13

class TestCollisions(Env):
    def test_personal_claude_skill_blocks(self):
        (self.home / ".claude/skills/demo-testing-base").mkdir(parents=True)
        self.assertBlocked(self.plan(), "collision: personal skill")

    def test_personal_opencode_and_agents_skills_block(self):
        for base in (".config/opencode/skills", ".agents/skills"):
            with self.subTest(base=base):
                d = self.home / base / "demo-spring-guide"
                d.mkdir(parents=True)
                self.assertBlocked(self.plan(), "collision")
                shutil.rmtree(d)

    def test_project_opencode_skill_blocks(self):
        (self.proj / ".opencode/skills/demo-project-review").mkdir(parents=True)
        self.assertBlocked(self.plan(), "OpenCode requires unique names")

    def test_manual_skill_declaring_same_name_blocks(self):
        d = self.proj / ".claude/skills/other-folder"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("---\nname: demo-testing-base\ndescription: x\n---\n")
        self.assertBlocked(self.plan(), "declares name 'demo-testing-base'")

    def test_collision_blocks_apply_even_with_old_fingerprint(self):
        fp = self.plan().fingerprint
        (self.home / ".claude/skills/demo-testing-base").mkdir(parents=True)
        with self.assertRaises(ApprovalError):
            workflow.apply_project_sync(self.proj, self.approval_for(fp), commit=self.commit,
                                        source=str(self.lib), home=self.home)
        self.assertFalse((self.proj / ".tareq/skills.lock").exists())

    def test_opencode_disable_env_warns(self):
        os.environ["OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"] = "1"
        self.assertTrue(any("OPENCODE_DISABLE" in w for w in self.plan().warnings))


# --------------------------------------------------------------------------- R-14

class TestHashesAndPinning(Env):
    def test_library_content_changed_without_hash_update_is_rejected(self):
        md = self.lib / "library/testing/demo-testing-base/SKILL.md"
        md.write_text(md.read_text() + "tampered\n")
        tampered = self.lib_commit("tamper")
        with self.assertRaises(SyncError) as ctx:
            self.plan(tampered)
        self.assertIn("content-hash-mismatch", str(ctx.exception))

    def test_cached_checkout_tampering_detected(self):
        self.plan()
        work = Path(os.environ["TAREQ_CACHE"]) / "checkouts" / self.commit
        (work / "library/testing/demo-testing-base/SKILL.md").write_text("tampered")
        with self.assertRaises(library.LibraryError):
            self.plan()

    def test_post_write_corruption_restores_everything(self):
        before = snapshot(self.proj)
        plan = self.plan()

        def corrupt(step):
            if step == "verify:before":
                (self.proj / ".claude/skills/demo-testing-base/SKILL.md").write_text("corrupted")
        with self.assertRaises(SyncError) as ctx:
            self.apply_locked(plan, fault_hook=corrupt)
        self.assertIn("hash mismatch", str(ctx.exception))
        self.assertEqual(snapshot(self.proj), before)


# --------------------------------------------------------------------------- R-15 / R-20

class TestApprovalFingerprint(Env):
    def test_r15_summary_lists_changes(self):
        s = self.plan().summary
        for text in ("Skills added:     demo-project-review, demo-spring-guide, demo-testing-base",
                     "Budget:           0 -> 3 of 10", "Library commit:   " + self.commit,
                     "ready; apply requires this fingerprint"):
            self.assertIn(text, s)

    def test_r15_blocked_plan_cannot_be_applied(self):
        (self.home / ".claude/skills/demo-testing-base").mkdir(parents=True)
        plan = self.plan()
        with self.assertRaises(SyncError):
            self.apply_locked(plan)

    def test_r20_wrong_fingerprint_refused(self):
        before = snapshot(self.proj)
        with self.assertRaises(ApprovalError) as ctx:
            workflow.apply_project_sync(self.proj, self.approval_for("sha256:" + "0" * 64),
                                        commit=self.commit, source=str(self.lib), home=self.home)
        self.assertIn("R-20", str(ctx.exception))
        self.assertEqual(snapshot(self.proj), before)

    def test_r20_fingerprint_binds_destination_state(self):
        fp = self.plan().fingerprint
        (self.proj / "opencode.json").write_text(json.dumps({"theme": "dark"}))
        self.assertNotEqual(self.plan().fingerprint, fp)
        with self.assertRaises(ApprovalError):
            workflow.apply_project_sync(self.proj, self.approval_for(fp), commit=self.commit,
                                        source=str(self.lib), home=self.home)

    def test_r20_fingerprint_binds_source_commit(self):
        fp = self.plan().fingerprint
        (self.lib / "README.md").write_text("new commit, same skills")
        newer = self.lib_commit("readme")
        self.assertNotEqual(self.plan(newer).fingerprint, fp)
        with self.assertRaises(ApprovalError):
            workflow.apply_project_sync(self.proj, self.approval_for(fp), commit=newer,
                                        source=str(self.lib), home=self.home)

    def test_r20_fingerprint_binds_operations_and_config(self):
        fp = self.plan().fingerprint
        self.edit_config(lambda d: d["include"].append("demo-pentest"))
        self.assertNotEqual(self.plan().fingerprint, fp)

    def test_r20_fingerprint_binds_source_hashes(self):
        fp = self.plan().fingerprint
        md = self.lib / "library/testing/demo-testing-base/SKILL.md"
        md.write_text(md.read_text() + "v2\n")
        self.edit_lib_yaml("catalog/skills.yaml", lambda d: next(
            s for s in d["skills"] if s["id"] == "demo-testing-base")["source"].update(
            content_hash=v.content_hash(md.parent)))
        newer = self.lib_commit("update skill")
        plan2 = self.plan(newer)
        self.assertNotEqual(plan2.fingerprint, fp)
        self.assertNotEqual(plan2.desired.source_hashes["demo-testing-base"],
                            self.plan().desired.source_hashes["demo-testing-base"])


# --------------------------------------------------------------------------- R-19

class TestAtomicity(Env):
    def _second_sync_plan(self):
        (self.proj / "CLAUDE.md").write_text("keep\n")
        self.sync()
        self.edit_config(lambda d: d.update(packs=["core"], include=["demo-project-review", "demo-pentest"]))
        plan = self.plan()
        kinds = {o["op"] for o in plan.operations}
        self.assertTrue({"write", "delete", "write_lock", "append_history"} <= kinds, kinds)
        return plan

    def _record_steps(self, plan):
        """Step names of a successful apply, taken from a throwaway copy of the project."""
        probe = self.tmp / "probe-project"
        shutil.copytree(self.proj, probe)
        steps = []
        probe_plan, _ = workflow.plan_project_sync(probe, source=str(self.lib), commit=self.commit,
                                                   home=self.home)
        self.assertEqual(probe_plan.fingerprint, plan.fingerprint)
        with lock_mod.project_lock(probe):
            apply_plan(probe, probe_plan, self.approval_for(probe_plan.fingerprint),
                       fault_hook=steps.append)
        shutil.rmtree(probe)
        return steps

    def test_caught_failure_at_every_step_restores_exact_state(self):
        plan = self._second_sync_plan()
        before = snapshot(self.proj)
        steps = self._record_steps(plan)
        self.assertGreater(len(steps), 20, steps)
        marker = steps.index("commit:marker")
        for index, name in enumerate(steps[:marker]):  # every step before the commit point
            with self.subTest(step=name):
                counter = {"n": -1}

                def fault(step, index=index, counter=counter):
                    counter["n"] += 1
                    if counter["n"] == index:
                        raise OSError(f"injected failure at {step}")
                with self.assertRaises(SyncError):
                    self.apply_locked(self.plan(), fault_hook=fault)
                self.assertEqual(snapshot(self.proj), before)
        lock = workflow.apply_project_sync(self.proj, self.approval_for(plan.fingerprint),
                                           commit=self.commit, source=str(self.lib), home=self.home)
        self.assertEqual(sorted(s["id"] for s in lock["skills"]),
                         ["demo-pentest", "demo-project-review", "demo-testing-base"])

    def test_failure_after_commit_marker_is_a_completed_sync(self):
        plan = self._second_sync_plan()
        for name in ("commit:marker", "commit:cleaned"):
            with self.subTest(step=name):
                def fault(step, name=name):
                    if step == name:
                        raise OSError("failure after the commit point")
                lock = self.apply_locked(self.plan(), fault_hook=fault)
                self.assertEqual(sorted(s["id"] for s in lock["skills"]),
                                 ["demo-pentest", "demo-project-review", "demo-testing-base"])
                self.assertFalse(txn_pending(self.proj))
                self.assertEqual({i.code for i in workflow.doctor(self.proj, home=self.home)
                                  if i.severity == "error"}, set())
                break  # the second iteration would re-plan an already applied state

    def test_no_temp_or_backup_files_left(self):
        self.sync()
        self.assertEqual([p for p in self.proj.rglob(".tareq-tmp-*")], [])
        self.assertFalse(txn_pending(self.proj))


# --------------------------------------------------------------------------- R-18 rollback

class TestRollback(Env):
    def setUp(self):
        super().setUp()
        (self.proj / "CLAUDE.md").write_text("project rules\n")
        manual = self.proj / ".claude/skills/my-own-skill"
        manual.mkdir(parents=True)
        (manual / "SKILL.md").write_text("---\nname: my-own-skill\ndescription: mine\n---\n")
        self.sync()
        self.rev1 = self.proj_commit("sync 1")
        self.state1 = snapshot(self.proj)
        self.edit_config(lambda d: d.update(packs=["core"], include=["demo-project-review", "demo-pentest"]))
        self.sync()
        self.proj_commit("sync 2")

    def rollback(self):
        plan, _ = workflow.plan_rollback(self.proj, self.rev1, source=str(self.lib), home=self.home)
        self.assertTrue(plan.ok, plan.summary)
        return plan, workflow.apply_rollback(self.proj, self.rev1, self.approval_for(plan.fingerprint),
                                             source=str(self.lib), home=self.home)

    def test_rollback_restores_generated_state_exactly(self):
        config_now = (self.proj / ".tareq/skills.yaml").read_bytes()
        plan, lock = self.rollback()
        self.assertIn("Rollback to:", plan.summary)
        after = snapshot(self.proj)
        generated1 = {g["path"]: g["hash"] for g in v.load_yaml(self.proj / ".tareq/skills.lock")["generated"]}
        for path, h in generated1.items():
            self.assertEqual(after[path], self.state1[path], path)
        self.assertFalse((self.proj / ".claude/skills/demo-pentest").exists())
        self.assertEqual((self.proj / ".tareq/skills.yaml").read_bytes(), config_now)  # never touched
        self.assertEqual(lock["rollback"], {"from_rev": self.rev1})
        self.assertEqual(after["CLAUDE.md"], self.state1["CLAUDE.md"])
        self.assertEqual(after[".claude/skills/my-own-skill/SKILL.md"],
                         self.state1[".claude/skills/my-own-skill/SKILL.md"])
        codes = {i.code for i in workflow.doctor(self.proj, home=self.home)}
        self.assertIn("config-differs", codes)

    def test_rollback_leaves_hand_edited_owned_file(self):
        f = self.proj / ".claude/skills/demo-pentest/SKILL.md"
        f.write_text(f.read_text() + "edited\n")
        plan, _ = self.rollback()
        self.assertIn("left untouched", plan.summary)
        self.assertIn("edited", f.read_text())

    def test_rollback_never_removes_manual_files_or_settings(self):
        claude = self.proj / ".claude/settings.json"
        data = json.loads(claude.read_text())
        data["permissions"] = {"allow": ["Read"]}
        claude.write_text(json.dumps(data))
        self.rollback()
        after = json.loads(claude.read_text())
        self.assertEqual(after["permissions"], {"allow": ["Read"]})
        self.assertNotIn("demo-pentest", after.get("skillOverrides", {}))

    def test_rollback_wrong_fingerprint_refused(self):
        before = snapshot(self.proj)
        with self.assertRaises(ApprovalError):
            workflow.apply_rollback(self.proj, self.rev1, self.approval_for("sha256:" + "1" * 64),
                                    source=str(self.lib), home=self.home)
        self.assertEqual(snapshot(self.proj), before)

    def test_rollback_is_atomic(self):
        plan, _ = workflow.plan_rollback(self.proj, self.rev1, source=str(self.lib), home=self.home)
        before = snapshot(self.proj)

        def fault(step):
            if step == "op:%d:before" % next(i for i, o in enumerate(plan.operations) if o["op"] == "write_lock"):
                raise OSError("injected")
        with self.assertRaises(SyncError):
            workflow.apply_rollback(self.proj, self.rev1, self.approval_for(plan.fingerprint),
                                    source=str(self.lib), home=self.home, fault_hook=fault)
        self.assertEqual(snapshot(self.proj), before)


# --------------------------------------------------------------------------- R-17 + doctor

class TestReportingAndDoctor(Env):
    def test_opencode_marked_not_tested(self):
        self.assertIn("NOT TESTED", self.plan().summary)
        self.sync()
        issues = workflow.doctor(self.proj, home=self.home, source=str(self.lib))
        self.assertIn("opencode-untested", {i.code for i in issues})
        self.assertNotIn("error", {i.severity for i in issues}, [str(i) for i in issues])

    def test_no_opencode_mention_without_opencode_target(self):
        self.edit_config(lambda d: d.update(targets=["claude-code"]))
        self.assertNotIn("OpenCode", self.plan().summary)

    def test_doctor_detects_drift_and_collisions(self):
        self.sync()
        (self.proj / ".claude/skills/demo-testing-base/SKILL.md").write_text("edited")
        (self.home / ".claude/skills/demo-project-review").mkdir(parents=True)
        self.edit_config(lambda d: d["budget"].update(max_descriptions=9))
        codes = {i.code for i in workflow.doctor(self.proj, home=self.home)}
        self.assertTrue({"generated-modified", "collision", "stale-lock"} <= codes, codes)


# --------------------------------------------------------------------------- intake

class TestIntake(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        shutil.copytree(FIX / "catalog", self.repo / "catalog")
        shutil.copytree(ROOT / "catalog" / "schema", self.repo / "catalog" / "schema")
        shutil.copytree(FIX / "library", self.repo / "library")
        self.src = Path(self._tmp.name) / "src" / "new-skill"
        self.src.mkdir(parents=True)
        (self.src / "SKILL.md").write_text("---\nname: new-skill\ndescription: A new skill.\n---\nbody\n")
        (self.src / "run.sh").write_text("touch /tmp/should-never-run\n")

    def tearDown(self):
        self._tmp.cleanup()

    def test_authored_skill_added_as_candidate(self):
        entry = workflow.add_skill(self.repo, self.src, skill_id="new-skill", category="testing",
                                   scope="general", version="0.1.0", authored=True)
        self.assertEqual((entry["status"], entry["review"]["state"]), ("candidate", "pending"))
        self.assertEqual(entry["source"]["type"], "local")
        self.assertTrue((self.repo / "library/testing/new-skill/SOURCE.txt").is_file())
        self.assertEqual(v.content_hash(self.repo / "library/testing/new-skill"), entry["source"]["content_hash"])
        issues = v.validate(self.repo / "catalog")
        self.assertEqual({i.code for i in issues if i.severity == "error"}, set())

    def test_authored_skill_can_record_where_it_was_derived_from(self):
        sha = "a" * 40
        entry = workflow.add_skill(self.repo, self.src, skill_id="new-skill", category="testing", scope="general",
                                   version="1.0.0", authored=True, url="https://github.com/example/proj", commit=sha)
        self.assertEqual((entry["source"]["type"], entry["source"]["url"], entry["source"]["commit"]),
                         ("local", "https://github.com/example/proj", sha))
        text = (self.repo / "library/testing/new-skill/SOURCE.txt").read_text()
        self.assertIn(f"derived-from: https://github.com/example/proj @ {sha}", text)
        self.assertNotIn("tareq-skills", text)
        self.assertEqual({i.code for i in v.validate(self.repo / "catalog") if i.severity == "error"}, set())

    def test_authored_derived_commit_must_be_full(self):
        before = snapshot(self.repo)
        with self.assertRaises(SyncError):
            workflow.add_skill(self.repo, self.src, skill_id="new-skill", category="testing", scope="general",
                               version="1", authored=True, url="https://github.com/example/proj", commit="main")
        self.assertEqual(snapshot(self.repo), before)

    def test_third_party_requires_pinned_commit(self):
        with self.assertRaises(SyncError):
            workflow.add_skill(self.repo, self.src, skill_id="new-skill", category="testing",
                               scope="general", version="1", authored=False, url="https://example.com/x",
                               commit="main", license_id="MIT")

    def test_name_mismatch_rejected_and_repo_unchanged(self):
        before = snapshot(self.repo)
        with self.assertRaises(SyncError):
            workflow.add_skill(self.repo, self.src, skill_id="other-id", category="testing",
                               scope="general", version="1", authored=True)
        self.assertEqual(snapshot(self.repo), before)

    def test_invalid_entry_rolled_back(self):
        before = snapshot(self.repo)
        with self.assertRaises(SyncError):
            workflow.add_skill(self.repo, self.src, skill_id="new-skill", category="not-declared",
                               scope="general", version="1", authored=True)
        self.assertEqual(snapshot(self.repo), before)

    def test_path_traversal_in_category_or_id_rejected(self):
        before = snapshot(self.repo.parent)
        for kw in ({"skill_id": "new-skill", "category": "../escape"},
                   {"skill_id": "../new-skill", "category": "testing"}):
            with self.subTest(**kw), self.assertRaisesRegex(SyncError, "^invalid (id|category)"):
                workflow.add_skill(self.repo, self.src, scope="general", version="1", authored=True, **kw)
        self.assertEqual(snapshot(self.repo.parent), before)

    def test_symlink_rejected(self):
        (self.src / "link").symlink_to("/etc/hostname")
        with self.assertRaises(SyncError):
            workflow.add_skill(self.repo, self.src, skill_id="new-skill", category="testing",
                               scope="general", version="1", authored=True)

    def test_scripts_never_executed(self):
        workflow.add_skill(self.repo, self.src, skill_id="new-skill", category="testing",
                           scope="general", version="1", authored=True)
        self.assertFalse(Path("/tmp/should-never-run").exists())

    def test_note_appended(self):
        proj = Path(self._tmp.name) / "proj"
        proj.mkdir()
        workflow.add_note(proj, "lessons", "Prefer verbatim copies.")
        workflow.add_note(proj, "decisions", "Second entry.")
        text = (proj / ".tareq/history.md").read_text()
        self.assertIn("note [lessons]", text)
        self.assertLess(text.index("Prefer verbatim"), text.index("Second entry"))


if __name__ == "__main__":
    unittest.main()
