"""Command-line interface: `bin/tareq <command> ...`. Exit 0 on success, 1 on failure/blocked."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import validate_catalog as v  # noqa: E402

from . import library, scan as scan_mod, selection, workflow  # noqa: E402
from .sync import CONFIG_FILE, SyncError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _local_catalog(path: Path) -> v.Catalog:
    cat, issues = v.load_catalog(path)
    if cat is None:
        raise SyncError("catalog invalid: " + "; ".join(map(str, issues)))
    return cat


def cmd_scan(a) -> int:
    cat = _local_catalog(a.catalog)
    found = scan_mod.scan(a.project, cat.stacks)
    for sid, evidence in found.items():
        print(f"{sid}: {'; '.join(evidence)}")
    if not found:
        print("no known stacks detected")
    return 0


def cmd_select(a) -> int:
    cat = _local_catalog(a.catalog)
    detected = set(scan_mod.scan(a.project, cat.stacks))
    proposal = selection.propose(cat, detected, set(a.tags.split(",")) if a.tags else None)
    print(json.dumps({"detected_stacks": sorted(detected), **proposal}, indent=2, default=list))
    if a.init:
        path = a.project / CONFIG_FILE
        if path.exists():
            print(f"{CONFIG_FILE} already exists; not modified", file=sys.stderr)
            return 1
        if not a.repo or not a.ref:
            print("--init needs --repo and --ref", file=sys.stderr)
            return 1
        path.parent.mkdir(parents=True, exist_ok=True)
        cfg = {"schema_version": 1, "project": a.name or a.project.resolve().name.lower(),
               "catalog": {"repo": a.repo, "ref": a.ref}, **proposal["config"],
               "budget": {"max_descriptions": v.DEFAULT_MAX_DESCRIPTIONS},
               "targets": a.targets.split(",")}
        import yaml
        path.write_text("# tareq-skills project configuration (maintained by the owner).\n"
                        + yaml.safe_dump(cfg, sort_keys=False))
        print(f"wrote {CONFIG_FILE} (proposal only; review before planning a sync)")
    return 1 if proposal["needs_owner_decision"] else 0


def _print_plan(plan, ctx, extra_apply: str) -> int:
    print(plan.summary)
    if plan.ok:
        print(f"\nTo apply after owner approval:\n  bin/tareq {extra_apply} --apply {plan.fingerprint}"
              f" --commit {ctx.commit}")
    return 0 if plan.ok else 1


def cmd_sync(a) -> int:
    kw = dict(source=a.library, home=a.home, adopt=set(a.adopt), approve_overwrite=set(a.approve_overwrite))
    base = f"sync --project {a.project}" + (f" --library {a.library}" if a.library else "") + \
        "".join(f" --adopt {x}" for x in a.adopt) + "".join(f" --approve-overwrite {x}" for x in a.approve_overwrite)
    if a.apply:
        if not a.commit:
            print("--apply requires --commit (the exact commit shown by the plan)", file=sys.stderr)
            return 1
        lock = workflow.apply_project_sync(a.project, a.apply, commit=a.commit, **kw)
        print(f"applied: {len(lock['skills'])} skill(s) at {lock['catalog']['commit']}")
        return 0
    plan, ctx = workflow.plan_project_sync(a.project, ref=a.ref, commit=a.commit, **kw)
    return _print_plan(plan, ctx, base)


def cmd_rollback(a) -> int:
    if a.apply:
        lock = workflow.apply_rollback(a.project, a.to, a.apply, source=a.library, home=a.home)
        print(f"rolled back to {a.to}: {len(lock['skills'])} skill(s)")
        return 0
    plan, ctx = workflow.plan_rollback(a.project, a.to, source=a.library, home=a.home)
    print(plan.summary)
    if plan.ok:
        print(f"\nTo apply after owner approval:\n  bin/tareq rollback --project {a.project} --to {a.to}"
              + (f" --library {a.library}" if a.library else "") + f" --apply {plan.fingerprint}")
    return 0 if plan.ok else 1


def cmd_doctor(a) -> int:
    issues = workflow.doctor(a.project, home=a.home, source=a.library)
    for i in issues:
        print(i)
    errors = sum(i.severity == "error" for i in issues)
    print(f"{errors} error(s), {len(issues) - errors} warning(s)")
    return 1 if errors else 0


def cmd_add_skill(a) -> int:
    entry = workflow.add_skill(REPO_ROOT, a.source_dir, skill_id=a.id, category=a.category,
                               scope=a.scope, version=a.version, authored=a.authored, url=a.url,
                               commit=a.commit, license_id=a.license,
                               stacks=a.stacks.split(",") if a.stacks else None, project_name=a.project_name)
    print(f"added '{entry['id']}' as candidate (review pending); content {entry['source']['content_hash']}")
    return 0


def cmd_note(a) -> int:
    workflow.add_note(a.project, a.category, a.text)
    print("note appended to .tareq/history.md")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tareq", description="tareq-skills manager")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def project_arg(p):
        p.add_argument("--project", type=Path, required=True, help="client project root")

    p = sub.add_parser("scan", help="detect project technologies")
    project_arg(p)
    p.add_argument("--catalog", type=Path, default=REPO_ROOT / "catalog")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("select", help="propose the smallest suitable skill set")
    project_arg(p)
    p.add_argument("--catalog", type=Path, default=REPO_ROOT / "catalog")
    p.add_argument("--tags", help="comma-separated tags to narrow the proposal")
    p.add_argument("--init", action="store_true", help=f"write {CONFIG_FILE} if it does not exist")
    p.add_argument("--repo"), p.add_argument("--ref"), p.add_argument("--name")
    p.add_argument("--targets", default="claude-code,opencode")
    p.set_defaults(fn=cmd_select)

    for name, fn, helptext in (("sync", cmd_sync, "plan or apply a synchronization"),
                               ("rollback", cmd_rollback, "plan or apply a rollback")):
        p = sub.add_parser(name, help=helptext)
        project_arg(p)
        p.add_argument("--library", help="library git source (default: catalog.repo)")
        p.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
        p.add_argument("--apply", metavar="FINGERPRINT", help="apply the approved plan")
        if name == "sync":
            p.add_argument("--ref"), p.add_argument("--commit")
            p.add_argument("--adopt", action="append", default=[],
                           help="take over an identical existing project skill")
            p.add_argument("--approve-overwrite", action="append", default=[],
                           help="owner-approved overwrite of an unmanaged project skill")
        else:
            p.add_argument("--to", required=True, help="client-repo git revision holding the target lock")
        p.set_defaults(fn=fn)

    p = sub.add_parser("doctor", help="read-only project health check")
    project_arg(p)
    p.add_argument("--library")
    p.add_argument("--home", type=Path, default=Path.home(), help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("add-skill", help="add a skill to the library as candidate")
    p.add_argument("source_dir", type=Path)
    p.add_argument("--id", required=True), p.add_argument("--category", required=True)
    p.add_argument("--scope", default="general", choices=["general", "stack", "project"])
    p.add_argument("--version", required=True)
    p.add_argument("--authored", action="store_true", help="internal / authored skill (D-23)")
    p.add_argument("--url"), p.add_argument("--commit"), p.add_argument("--license")
    p.add_argument("--stacks"), p.add_argument("--project-name")
    p.set_defaults(fn=cmd_add_skill)

    p = sub.add_parser("note", help="append a categorized note or lesson to .tareq/history.md")
    project_arg(p)
    p.add_argument("--category", required=True)
    p.add_argument("text")
    p.set_defaults(fn=cmd_note)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (SyncError, library.LibraryError, v.FrontmatterError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
