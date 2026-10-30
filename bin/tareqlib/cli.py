"""Command-line interface: `bin/tareq <command> ...`.

Exit codes: 0 success, 1 failure or blocked plan, 2 approval unavailable or denied.
There is deliberately no flag or environment variable that skips or simulates approval, and
no way to redirect the collision-check home directory (D-26, F3)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import validate_catalog as v  # noqa: E402

from . import approval as approval_mod, library, lock as lock_mod, scan as scan_mod, selection, workflow  # noqa: E402
from .fsutil import UnsafePathError  # noqa: E402
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
        if not a.repo or not a.ref:
            print("--init needs --repo and --ref", file=sys.stderr)
            return 1
        import yaml
        cfg = {"schema_version": 1, "project": a.name or a.project.resolve().name.lower(),
               "catalog": {"repo": a.repo, "ref": a.ref}, **proposal["config"],
               "budget": {"max_descriptions": v.DEFAULT_MAX_DESCRIPTIONS},
               "targets": a.targets.split(",")}
        workflow.init_config(a.project, "# tareq-skills project configuration (maintained by the owner).\n"
                             + yaml.safe_dump(cfg, sort_keys=False))
        print(f"wrote {CONFIG_FILE} (proposal only; review before planning a sync)")
    return 1 if proposal["needs_owner_decision"] else 0


def _print_plan(plan, ctx, extra_apply: str) -> int:
    print(plan.summary)
    if plan.ok:
        print("\nApplying needs an explicit confirmation typed by a person on an interactive "
              "terminal; it is refused anywhere else.\nTo apply, run in a terminal:\n  "
              f"bin/tareq {extra_apply} --apply {plan.fingerprint}" + (f" --commit {ctx.commit}" if ctx else ""))
    return 0 if plan.ok else 1


def _approve(plan, action: str) -> approval_mod.Approval:
    """The only way to obtain an Approval from the CLI: a human on the controlling terminal."""
    return approval_mod.request_tty_approval(summary=plan.summary, fingerprint=plan.fingerprint,
                                             action=action)


def cmd_sync(a) -> int:
    kw = dict(source=a.library, adopt=set(a.adopt), approve_overwrite=set(a.approve_overwrite))
    base = f"sync --project {a.project}" + (f" --library {a.library}" if a.library else "") + \
        "".join(f" --adopt {x}" for x in a.adopt) + "".join(f" --approve-overwrite {x}" for x in a.approve_overwrite)
    if not a.apply:
        plan, ctx = workflow.plan_project_sync(a.project, ref=a.ref, commit=a.commit, **kw)
        return _print_plan(plan, ctx, base)
    if not a.commit:
        print("--apply requires --commit (the exact commit shown by the plan)", file=sys.stderr)
        return 1
    plan, _ = workflow.plan_project_sync(a.project, commit=a.commit, **kw)
    if not plan.ok:
        print(plan.summary)
        return 1
    if plan.fingerprint != a.apply:
        print("error: the plan changed since it was shown (fingerprint mismatch); nothing was "
              f"applied. Current fingerprint: {plan.fingerprint}", file=sys.stderr)
        return 1
    approval = _approve(plan, "synchronize this project")
    lock = workflow.apply_project_sync(a.project, approval, commit=a.commit, source=a.library,
                                       adopt=set(a.adopt), approve_overwrite=set(a.approve_overwrite))
    print(f"applied: {len(lock['skills'])} skill(s) at {lock['catalog']['commit']}")
    return 0


def cmd_rollback(a) -> int:
    plan, ctx = workflow.plan_rollback(a.project, a.to, source=a.library)
    if not a.apply:
        print(plan.summary)
        if plan.ok:
            print("\nApplying needs an explicit confirmation typed by a person on an interactive "
                  f"terminal.\nTo apply, run in a terminal:\n  bin/tareq rollback --project {a.project} "
                  f"--to {a.to}" + (f" --library {a.library}" if a.library else "")
                  + f" --apply {plan.fingerprint}")
        return 0 if plan.ok else 1
    if not plan.ok:
        print(plan.summary)
        return 1
    if plan.fingerprint != a.apply:
        print("error: the plan changed since it was shown (fingerprint mismatch); nothing was "
              f"applied. Current fingerprint: {plan.fingerprint}", file=sys.stderr)
        return 1
    approval = _approve(plan, f"roll back this project to {a.to}")
    lock = workflow.apply_rollback(a.project, a.to, approval, source=a.library)
    print(f"rolled back to {a.to}: {len(lock['skills'])} skill(s)")
    return 0


def cmd_recover(a) -> int:
    result = workflow.recover_project(a.project)
    print({"rolled-back": "interrupted transaction rolled back; the project is in its pre-sync state",
           "committed": "completed transaction cleaned up",
           "discarded": "incomplete transaction discarded; nothing had been modified",
           None: "nothing to recover"}[result])
    return 0


def cmd_doctor(a) -> int:
    issues = workflow.doctor(a.project, source=a.library)
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
    # allow_abbrev=False: a prefix like `--approve` must never silently mean `--approve-overwrite`.
    ap = argparse.ArgumentParser(prog="tareq", description="tareq-skills manager", allow_abbrev=False)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def project_arg(p):
        p.add_argument("--project", type=Path, required=True, help="client project root")

    _add_parser = sub.add_parser
    sub.add_parser = lambda *args, **kw: _add_parser(*args, allow_abbrev=False, **kw)

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
        p.add_argument("--apply", metavar="FINGERPRINT",
                       help="apply this plan after you confirm it on an interactive terminal")
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
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("recover", help="repair an interrupted sync/rollback (restores the pre-sync state)")
    project_arg(p)
    p.set_defaults(fn=cmd_recover)

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
    except approval_mod.ApprovalError as exc:
        print(f"error: approval not established: {exc}", file=sys.stderr)
        return 2
    except (SyncError, library.LibraryError, v.FrontmatterError, lock_mod.ProjectBusy,
            UnsafePathError, workflow.txn.TransactionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
