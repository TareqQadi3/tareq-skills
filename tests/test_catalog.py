"""Behavioral tests for bin/validate_catalog.py (M1).

Each negative test copies the synthetic fixtures to a temp directory, applies one
mutation, runs the real validator, and asserts the specific error code it must raise.
Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

import validate_catalog as v  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def codes(issues, severity="error"):
    return {i.code for i in issues if i.severity == severity}


class Workspace:
    """Temp copy of the fixture catalog + project, with YAML edit helpers."""

    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        shutil.copytree(FIXTURES / "catalog", self.root / "catalog")
        shutil.copytree(FIXTURES / "project", self.root / "project")
        self.catalog = self.root / "catalog"
        self.project = self.root / "project"

    def close(self):
        self._tmp.cleanup()

    def edit(self, rel: str, fn):
        path = self.root / rel
        data = yaml.safe_load(path.read_text())
        fn(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    def write(self, rel: str, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    def skill(self, data, sid):
        return next(s for s in data["skills"] if s["id"] == sid)

    def edit_skill(self, sid, fn):
        self.edit("catalog/skills.yaml", lambda d: fn(self.skill(d, sid)))

    def validate(self, with_project=False):
        return v.validate(self.catalog, self.project if with_project else None)


class Base(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()

    def tearDown(self):
        self.ws.close()

    def assertError(self, code, with_project=False):
        issues = self.ws.validate(with_project)
        self.assertIn(code, codes(issues), f"expected '{code}', got: {[str(i) for i in issues]}")


# --------------------------------------------------------------------------- positive

class TestValidFixtures(unittest.TestCase):
    def test_real_catalog_is_valid(self):
        issues = v.validate(ROOT / "catalog")
        self.assertEqual(codes(issues), set(), [str(i) for i in issues])

    def test_fixture_catalog_and_project_are_valid(self):
        issues = v.validate(FIXTURES / "catalog", FIXTURES / "project")
        self.assertEqual(codes(issues), set(), [str(i) for i in issues])

    def test_cross_level_conflict_resolved_by_priority(self):
        cat, _ = v.load_catalog(FIXTURES / "catalog")
        cfg = v.load_yaml(FIXTURES / "project" / ".tareq" / "skills.yaml")
        selected, dropped = v.resolve_project_skills(cfg, cat)
        self.assertIn("demo-project-review", selected)
        self.assertNotIn("demo-ui-review-general", selected)
        self.assertEqual(dropped, [("demo-ui-review-general", "demo-project-review")])

    def test_cli_exit_codes(self):
        self.assertEqual(v.main(["--catalog", str(ROOT / "catalog")]), 0)
        ws = Workspace()
        try:
            ws.edit_skill("demo-testing-base", lambda s: s.update(status="bogus"))
            self.assertEqual(v.main(["--catalog", str(ws.catalog)]), 1)
        finally:
            ws.close()


# --------------------------------------------------------------------------- YAML / schema

class TestYamlAndSchema(Base):
    def test_malformed_yaml_rejected(self):
        with self.assertRaises(yaml.YAMLError):
            v.load_yaml(FIXTURES / "invalid" / "malformed.yaml")

    def test_duplicate_yaml_key_rejected(self):
        with self.assertRaises(v.DuplicateKeyError):
            v.load_yaml(FIXTURES / "invalid" / "duplicate-key.yaml")

    def test_invalid_status(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s.update(status="enabled"))
        self.assertError("schema")

    def test_short_commit_rejected(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s["source"].update(commit="abc123"))
        self.assertError("schema")

    def test_upstream_requires_commit(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s["source"].pop("commit"))
        self.assertError("schema")

    def test_project_scope_requires_project(self):
        self.ws.edit_skill("demo-project-review", lambda s: s.pop("project"))
        self.assertError("schema")

    def test_unknown_field_rejected(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s.update(auto_update=True))
        self.assertError("schema")

    def test_approved_review_requires_reviewer(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s["review"].pop("reviewed_by"))
        self.assertError("schema")

    def test_overlay_cannot_change_status_or_path(self):
        self.ws.edit("catalog/overlays/demo-ui-review-general.yaml",
                     lambda d: d["set"].update(status="active", path="library/x/y"))
        self.assertError("schema")

    def test_stack_rule_needs_exactly_one_kind(self):
        self.ws.edit("catalog/stacks.yaml", lambda d: d["stacks"][0]["detect"]["any"].append(
            {"file": "a", "dependency": {"ecosystem": "npm", "name": "x"}}))
        self.assertError("schema")

    def test_invalid_project_config(self):
        cat, _ = v.load_catalog(FIXTURES / "catalog")
        cfg = v.load_yaml(FIXTURES / "invalid" / "project-config.yaml")
        issues = v.check_project_config(cfg, cat, "cfg")
        self.assertIn("schema", codes(issues))
        self.assertGreaterEqual(len(issues), 4, [str(i) for i in issues])

    def test_invalid_lock(self):
        lock = v.load_yaml(FIXTURES / "invalid" / "lock.yaml")
        issues = v.check_lock(lock, None, "lock")
        self.assertIn("schema", codes(issues))
        self.assertGreaterEqual(len(issues), 4, [str(i) for i in issues])


# --------------------------------------------------------------------------- catalog rules

class TestCatalogRules(Base):
    def test_duplicate_skill_id(self):
        def dup(d):
            d["skills"].append(dict(self.ws.skill(d, "demo-testing-base")))
        self.ws.edit("catalog/skills.yaml", dup)
        self.assertError("duplicate-id")

    def test_unknown_category(self):
        self.ws.edit_skill("demo-testing-base",
                           lambda s: s.update(category="qa", path="library/qa/demo-testing-base"))
        self.assertError("unknown-category")

    def test_path_must_match_category_and_id(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s.update(path="library/testing/other"))
        self.assertError("path-mismatch")

    def test_unknown_skill_reference(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s.update(conflicts_with=["ghost"]))
        self.assertError("unknown-skill")

    def test_unknown_stack_reference(self):
        self.ws.edit_skill("demo-spring-guide", lambda s: s.update(stacks=["cobol"]))
        self.assertError("unknown-stack")

    def test_self_reference(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s.update(requires=["demo-testing-base"]))
        self.assertError("self-reference")

    def test_asymmetric_conflict(self):
        self.ws.edit_skill("demo-ui-review-general", lambda s: s.pop("conflicts_with"))
        self.assertError("asymmetric-conflict")

    def test_requires_and_conflicts_same_skill(self):
        def both(d):
            a, b = self.ws.skill(d, "demo-spring-guide"), self.ws.skill(d, "demo-testing-base")
            a["conflicts_with"] = ["demo-testing-base"]
            b["conflicts_with"] = ["demo-spring-guide"]
        self.ws.edit("catalog/skills.yaml", both)
        self.assertError("requires-conflict")

    def test_requires_cycle(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s.update(requires=["demo-spring-guide"]))
        self.assertError("requires-cycle")

    def test_missing_dependency_for_active_skill(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s.update(status="disabled"))
        self.assertError("missing-dependency")

    def test_active_requires_approved_review(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s.update(review={"state": "pending"}))
        self.assertError("active-unreviewed")

    def test_rejected_must_be_disabled(self):
        self.ws.edit_skill("demo-unlicensed", lambda s: s.update(
            review={"state": "rejected", "reviewed_by": "owner", "date": "2026-10-29"}))
        self.assertError("rejected-not-disabled")

    def test_unlicensed_cannot_be_active(self):
        self.ws.edit_skill("demo-unlicensed", lambda s: s.update(
            status="active", review={"state": "approved", "reviewed_by": "owner", "date": "2026-10-29"}))
        self.assertError("license-not-accepted")

    def test_non_accepted_license_cannot_be_active(self):
        self.ws.edit_skill("demo-testing-base", lambda s: s["source"].update(license="GPL-3.0-only"))
        self.assertError("license-not-accepted")

    def test_license_exception_allows_activation(self):
        self.ws.edit_skill("demo-unlicensed", lambda s: s.update(
            status="active",
            review={"state": "approved", "reviewed_by": "owner", "date": "2026-10-29"},
            license_exception={"approved_by": "owner", "date": "2026-10-29", "reason": "test"}))
        self.assertNotIn("license-not-accepted", codes(self.ws.validate()))

    def test_offensive_active_skill_must_be_isolated(self):
        self.ws.edit_skill("demo-pentest", lambda s: s["risk"].update(isolated_env_only=False))
        self.assertError("offensive-unrestricted")

    def test_replaced_skill_cannot_stay_active(self):
        self.ws.edit_skill("demo-old-spring", lambda s: s.update(status="active"))
        self.assertError("replaced-still-active")

    def test_stack_implies_cycle(self):
        self.ws.edit("catalog/stacks.yaml",
                     lambda d: d["stacks"][0].update(implies=["spring-boot"]))
        self.assertError("implies-cycle")

    def test_bad_detection_regex(self):
        self.ws.edit("catalog/stacks.yaml", lambda d: d["stacks"][1]["detect"]["all"][0]
                     ["file_contains"].update(pattern="spring(boot"))
        self.assertError("bad-pattern")


class TestPacksAndOverlays(Base):
    def test_pack_cycle(self):
        self.ws.edit("catalog/packs/core.yaml", lambda d: d.update(includes=["backend-java"]))
        self.assertError("pack-cycle")

    def test_unknown_pack_include(self):
        self.ws.edit("catalog/packs/core.yaml", lambda d: d.update(includes=["ghost"]))
        self.assertError("unknown-pack")

    def test_pack_unknown_skill(self):
        self.ws.edit("catalog/packs/core.yaml", lambda d: d["skills"].append("ghost"))
        self.assertError("unknown-skill")

    def test_pack_disabled_skill(self):
        self.ws.edit("catalog/packs/core.yaml", lambda d: d["skills"].append("demo-old-spring"))
        self.assertError("pack-disabled-skill")

    def test_pack_candidate_skill_warns(self):
        self.ws.edit("catalog/packs/core.yaml", lambda d: d["skills"].append("demo-unlicensed"))
        self.assertIn("pack-candidate-skill", codes(self.ws.validate(), "warning"))

    def test_marketing_cannot_be_default(self):
        self.ws.edit("catalog/packs/marketing.yaml", lambda d: d.update(default=True))
        self.assertError("default-pack-marketing")

    def test_marketing_not_reachable_from_default_pack(self):
        self.ws.edit("catalog/packs/core.yaml", lambda d: d.update(includes=["marketing"]))
        self.assertError("default-pack-marketing")

    def test_pack_with_conflicting_skills(self):
        self.ws.edit("catalog/packs/core.yaml",
                     lambda d: d["skills"].extend(["demo-project-review", "demo-ui-review-general"]))
        self.assertError("pack-conflict")

    def test_pack_file_name_must_match_id(self):
        self.ws.edit("catalog/packs/core.yaml", lambda d: d.update(id="basics"))
        self.assertError("file-name")

    def test_overlay_unknown_skill(self):
        self.ws.write("catalog/overlays/ghost.yaml",
                      {"schema_version": 1, "skill": "ghost", "reason": "x", "set": {"invocation": "manual"}})
        self.assertError("unknown-skill")

    def test_overlay_does_not_modify_catalog_or_library(self):
        before = (self.ws.catalog / "skills.yaml").read_bytes()
        cat, _ = v.load_catalog(self.ws.catalog)
        self.assertEqual(cat.skills["demo-ui-review-general"]["invocation"], "auto")
        self.assertEqual(v.effective_invocation("demo-ui-review-general", cat), "manual")
        self.assertEqual((self.ws.catalog / "skills.yaml").read_bytes(), before)


# --------------------------------------------------------------------------- project config + lock

class TestProjectConfigAndLock(Base):
    def test_unknown_pack_in_config(self):
        self.ws.edit("project/.tareq/skills.yaml", lambda d: d["packs"].append("ghost"))
        self.assertError("unknown-pack", with_project=True)

    def test_include_exclude_overlap(self):
        self.ws.edit("project/.tareq/skills.yaml", lambda d: d.update(exclude=["demo-project-review"]))
        self.assertError("include-exclude-overlap", with_project=True)

    def test_candidate_cannot_be_enabled(self):
        self.ws.edit("project/.tareq/skills.yaml", lambda d: d["include"].append("demo-unlicensed"))
        self.assertError("inactive-skill-selected", with_project=True)

    def test_foreign_project_skill(self):
        self.ws.edit("project/.tareq/skills.yaml", lambda d: d.update(project="other-app"))
        self.assertError("foreign-project-skill", with_project=True)

    def test_excluding_dependency_fails(self):
        self.ws.edit("project/.tareq/skills.yaml", lambda d: d.update(exclude=["demo-testing-base"]))
        self.assertError("missing-dependency", with_project=True)

    def test_same_level_conflict_requires_owner_decision(self):
        def make_general(d):
            self.ws.skill(d, "demo-project-review").update(scope="general")
            self.ws.skill(d, "demo-project-review").pop("project")
        self.ws.edit("catalog/skills.yaml", make_general)
        self.assertError("unresolved-conflict", with_project=True)

    def test_budget_is_hard_maximum(self):
        self.ws.edit("project/.tareq/skills.yaml", lambda d: d["budget"].update(max_descriptions=2))
        self.assertError("budget-exceeded", with_project=True)

    def test_budget_default_is_40(self):
        self.assertEqual(v.DEFAULT_MAX_DESCRIPTIONS, 40)

    def test_stale_lock_detected(self):
        self.ws.edit("project/.tareq/skills.yaml", lambda d: d["budget"].update(max_descriptions=9))
        self.assertError("stale-lock", with_project=True)

    def test_lock_hash_mismatch(self):
        self.ws.edit("project/.tareq/skills.lock",
                     lambda d: d["skills"][0].update(content_hash="sha256:" + "9" * 64))
        self.assertError("hash-mismatch", with_project=True)

    def test_lock_commit_mismatch(self):
        self.ws.edit("project/.tareq/skills.lock",
                     lambda d: next(s for s in d["skills"] if s["id"] == "demo-testing-base")
                     ["source"].update(commit="1" * 40))
        self.assertError("commit-mismatch", with_project=True)

    def test_lock_pack_hash_mismatch(self):
        self.ws.edit("catalog/packs/core.yaml", lambda d: d.update(description="changed"))
        self.assertError("pack-mismatch", with_project=True)

    def test_lock_duplicate_skill(self):
        self.ws.edit("project/.tareq/skills.lock", lambda d: d["skills"].append(dict(d["skills"][0])))
        self.assertError("duplicate-id", with_project=True)

    def test_lock_with_conflicting_skills(self):
        def add_conflict(d):
            d["skills"].append({"id": "demo-ui-review-general", "version": "2.1.0",
                                "source": {"type": "upstream", "url": "https://example.com/ui-review",
                                           "commit": "a" * 40},
                                "content_hash": "sha256:" + "2" * 64, "license": "Apache-2.0",
                                "via": ["include"]})
        self.ws.edit("project/.tareq/skills.lock", add_conflict)
        self.assertError("unresolved-conflict", with_project=True)

    def test_lock_budget_used_over_max(self):
        self.ws.edit("project/.tareq/skills.lock", lambda d: d["budget"].update(used=11))
        self.assertError("budget-exceeded", with_project=True)


if __name__ == "__main__":
    unittest.main()
