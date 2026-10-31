"""High-level commands shared by the CLI and tests."""
from __future__ import annotations

import datetime as _dt
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import validate_catalog as v  # noqa: E402

from . import approval as approval_mod, library, lock as lock_mod, txn  # noqa: E402
from .fsutil import UnsafePathError, path_state, real_home, safe_dest, sha256_bytes, sha256_file  # noqa: E402
from .sync import (CONFIG_FILE, HISTORY_FILE, LOCK_FILE, SKILLS_DIR, TEMPLATES, Plan,  # noqa: E402
                   SyncError, apply_plan, build_desired, load_library_catalog, plan_sync, read_lock)


@dataclass
class Context:
    project: Path
    source: str
    commit: str
    checkout: Path
    config: dict | None
    catalog: v.Catalog | None = None


def load_config(project: Path) -> dict:
    path = project / CONFIG_FILE
    if not path.is_file():
        raise SyncError(f"{CONFIG_FILE} not found; run `tareq select --init` first")
    config = v.load_yaml(path)
    issues = v.schema_issues("project-config", config, CONFIG_FILE)
    if issues:
        raise SyncError("invalid project configuration: " + "; ".join(i.message for i in issues))
    return config


def _context(project: Path, source: str | None, ref: str | None, commit: str | None,
             config: dict | None) -> Context:
    src = source or (config or {}).get("catalog", {}).get("repo")
    if not src:
        raise SyncError("no library source; pass --library")
    if commit is None:
        commit = library.resolve_commit(src, ref or config["catalog"]["ref"])
    return Context(project.resolve(), src, commit, library.checkout(src, commit), config)


# --------------------------------------------------------------------------- sync

def _lock_verifier(source: str, current_commit: str, current_checkout: Path):
    """F4: corroborate an existing lock's skill files against the library at the lock's own
    commit, so a forged lock cannot make sync/rollback delete files tareq never generated."""
    def verify(lock: dict) -> list[str]:
        commit = lock["catalog"]["commit"]
        try:
            checkout = current_checkout if commit == current_commit else library.checkout(source, commit)
            problems: list[str] = []
            desired = build_desired(
                checkout=checkout, commit=commit, repo=lock["catalog"]["repo"],
                ref=lock["catalog"].get("ref"), project=lock["project"],
                resolved={e["id"]: e["via"] for e in lock["skills"]}, targets=lock["targets"],
                max_descriptions=lock["budget"]["max_descriptions"], config_hash=lock["config_hash"],
                blocks=[], warnings=[], pack_hashes={p["id"]: p["hash"] for p in lock["packs"]})
        except (SyncError, library.LibraryError) as exc:
            return [f"cannot verify the lock against the library at {lock['catalog']['commit'][:12]}: {exc}"]
        expected = {rel: sha256_bytes(data) for rel, data in desired.files.items()
                    if rel.startswith(SKILLS_DIR + "/")}
        claimed = {g["path"]: g["hash"] for g in lock["generated"] if g["path"].startswith(SKILLS_DIR + "/")}
        for rel in sorted(set(expected) | set(claimed)):
            if expected.get(rel) != claimed.get(rel):
                problems.append(f"'{rel}' is not what the library at {commit[:12]} generates")
        return problems
    return verify


def plan_project_sync(project: Path, *, source: str | None = None, ref: str | None = None,
                      commit: str | None = None, home: Path | None = None,
                      adopt=frozenset(), approve_overwrite=frozenset()) -> tuple[Plan, Context]:
    config = load_config(project)
    ctx = _context(project, source, ref, commit, config)
    blocks: list[str] = []
    warnings: list[str] = []
    cat = load_library_catalog(ctx.checkout)
    ctx.catalog = cat
    issues = v.check_project_config(config, cat, CONFIG_FILE)
    blocks += [str(i) for i in issues if i.severity == "error"]
    warnings += [f"[{i.code}] {i.message}" for i in issues if i.severity == "warning"]
    resolved, _ = v.resolve_project_skills(config, cat) if not blocks else ({}, [])
    desired = build_desired(
        checkout=ctx.checkout, commit=ctx.commit, repo=config["catalog"]["repo"],
        ref=config["catalog"].get("ref"), project=config["project"], resolved=resolved,
        targets=config["targets"],
        max_descriptions=config.get("budget", {}).get("max_descriptions", v.DEFAULT_MAX_DESCRIPTIONS),
        config_hash=sha256_file(project / CONFIG_FILE), blocks=blocks, warnings=warnings)
    plan = plan_sync(project, desired, home=home or real_home(), library_source=ctx.source,
                     blocks=blocks, warnings=warnings, adopt=set(adopt),
                     approve_overwrite=set(approve_overwrite),
                     verify_lock=_lock_verifier(ctx.source, ctx.commit, ctx.checkout))
    return plan, ctx


def recover_project(project: Path, hook=None) -> str | None:
    """Repair an interrupted sync/rollback (F2). Takes the project lock."""
    if not (project / ".tareq").is_dir():
        return None  # not a tareq project: nothing to recover, and do not create anything
    with lock_mod.project_lock(project):
        return txn.recover(project.resolve(), hook)


def apply_project_sync(project: Path, approval: approval_mod.Approval, *, commit: str,
                       source: str | None = None, home: Path | None = None,
                       adopt=frozenset(), approve_overwrite=frozenset(), fault_hook=None) -> dict:
    """Under the project lock: repair any interrupted transaction, recompute the plan from
    scratch, and apply it only if its fingerprint equals the one `approval` is bound to.
    Planning and writing happen under one lock, so nothing can change in between (F1)."""
    approval_mod.check_shape(approval)  # fail before taking the lock or doing any work
    with lock_mod.project_lock(project):
        txn.recover(project.resolve(), fault_hook)
        plan, ctx = plan_project_sync(project, source=source, commit=commit, home=home, adopt=adopt,
                                      approve_overwrite=approve_overwrite)
        return apply_plan(project, plan, approval, fault_hook=fault_hook,
                          checkout_catalog=ctx.catalog, config=ctx.config)


# --------------------------------------------------------------------------- rollback

def _lock_at(project: Path, rev: str) -> dict:
    if rev.startswith("-"):
        raise SyncError("invalid revision")
    proc = subprocess.run(["git", "-C", str(project), "show", f"{rev}:{LOCK_FILE}"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SyncError(f"no {LOCK_FILE} at revision {rev}: {proc.stderr.strip()[:200]}")
    lock = yaml.load(proc.stdout, Loader=v._StrictLoader)  # noqa: S506
    issues = v.schema_issues("lock", lock, f"{rev}:{LOCK_FILE}")
    if issues:
        raise SyncError(f"lock at {rev} is not a valid version-2 lock: {issues[0].message}")
    forged = v.check_lock_ownership(lock, f"{rev}:{LOCK_FILE}")
    if forged:  # a rollback target from git history is untrusted input (F4)
        raise SyncError(f"lock at {rev} makes forged ownership claims: {forged[0].message}")
    return lock


def plan_rollback(project: Path, rev: str, *, source: str | None = None,
                  home: Path | None = None) -> tuple[Plan, Context]:
    """Regenerate exactly the state recorded by the lock at `rev`. Touches only owned files
    and keys (R-18); never modifies .tareq/skills.yaml."""
    target = _lock_at(project, rev)
    config = load_config(project)
    trusted = config["catalog"]["repo"]
    if source is None and target["catalog"]["repo"] != trusted:
        raise SyncError(f"the lock at {rev} names library {target['catalog']['repo']!r}, which is not "
                        f"the project's configured library {trusted!r}; pass --library explicitly "
                        "if you trust it")
    ctx = _context(project, source or trusted, None, target["catalog"]["commit"], config)
    blocks: list[str] = []
    warnings: list[str] = []
    desired = build_desired(
        checkout=ctx.checkout, commit=ctx.commit, repo=target["catalog"]["repo"],
        ref=target["catalog"].get("ref"), project=target["project"],
        resolved={s["id"]: s["via"] for s in target["skills"]}, targets=target["targets"],
        max_descriptions=target["budget"]["max_descriptions"], config_hash=target["config_hash"],
        blocks=blocks, warnings=warnings,
        pack_hashes={p["id"]: p["hash"] for p in target["packs"]})
    ctx.catalog = desired.catalog
    expected = {g["path"]: g["hash"] for g in target["generated"]}
    from .fsutil import sha256_bytes
    produced = {rel: sha256_bytes(data) for rel, data in desired.files.items()}
    if produced != expected:
        diff = sorted(set(produced.items()) ^ set(expected.items()))
        blocks.append(f"cannot reproduce the generated state of {rev} exactly "
                      f"({len(diff)} differing entries, e.g. {diff[0][0]})")
    plan = plan_sync(project, desired, home=home or real_home(), library_source=ctx.source,
                     blocks=blocks, warnings=warnings, rollback_from=rev,
                     verify_lock=_lock_verifier(ctx.source, ctx.commit, ctx.checkout))
    return plan, ctx


def apply_rollback(project: Path, rev: str, approval: approval_mod.Approval, *,
                   source: str | None = None, home: Path | None = None, fault_hook=None) -> dict:
    approval_mod.check_shape(approval)
    with lock_mod.project_lock(project):
        txn.recover(project.resolve(), fault_hook)
        plan, ctx = plan_rollback(project, rev, source=source, home=home)
        return apply_plan(project, plan, approval, fault_hook=fault_hook,
                          checkout_catalog=ctx.catalog, config=None)


# --------------------------------------------------------------------------- doctor

def doctor(project: Path, *, home: Path | None = None, source: str | None = None) -> list[v.Issue]:
    """Read-only health check of a client project."""
    project = project.resolve()
    home = home or real_home()
    out: list[v.Issue] = []
    add = lambda sev, code, msg: out.append(v.Issue(sev, code, str(project), msg))  # noqa: E731
    blocks: list[str] = []
    if txn.pending(project):
        add("error", "txn-pending", "an interrupted sync/rollback left .tareq/.txn; run `tareq recover`")
    lock = read_lock(project, blocks)
    for b in blocks:
        add("error", "lock-invalid", b)
    config = None
    try:
        config = load_config(project)
    except (SyncError, OSError, yaml.YAMLError) as exc:
        add("error", "config-invalid", str(exc))
    if lock is None:
        if not blocks:
            add("warning", "not-synced", f"no {LOCK_FILE}; nothing has been synchronized yet")
        return out
    for g in lock["generated"]:
        st = path_state(project, g["path"])
        if st is None:
            add("error", "generated-missing", f"'{g['path']}' is missing")
        elif st != g["hash"]:
            add("error", "generated-modified", f"'{g['path']}' was edited by hand")
    if config is not None and sha256_file(project / CONFIG_FILE) != lock["config_hash"]:
        if "rollback" in lock:
            add("warning", "config-differs", f"rolled back to {lock['rollback']['from_rev']}; "
                f"{CONFIG_FILE} still describes a newer selection")
        else:
            add("warning", "stale-lock", f"{CONFIG_FILE} changed since the last sync; plan a new sync")
    ids = [s["id"] for s in lock["skills"]]
    for base in (home / ".claude/skills", home / ".config/opencode/skills", home / ".agents/skills"):
        for sid in ids:
            if (base / sid).exists():
                add("error", "collision", f"personal skill '{base / sid}' shadows or duplicates '{sid}'")
    owned_dirs = {s for s in ids}
    skills_root = project / SKILLS_DIR
    if skills_root.is_dir():
        manual = sorted(p.name for p in skills_root.iterdir() if p.is_dir() and p.name not in owned_dirs)
        if manual:
            add("warning", "manual-skills", f"{len(manual)} skill(s) not managed by tareq-skills "
                f"(left untouched): {', '.join(manual[:10])}{' …' if len(manual) > 10 else ''}")
    import os
    if "opencode" in lock["targets"]:
        for var in ("OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"):
            if os.environ.get(var):
                add("warning", "opencode-disabled", f"{var} is set")
        add("warning", "opencode-untested", "OpenCode output follows documented behavior only; NOT TESTED")
    if source is not None:
        try:
            checkout = library.checkout(source, lock["catalog"]["commit"])
            cat = load_library_catalog(checkout)
            for i in v.check_lock(lock, cat, LOCK_FILE, config,
                                  project / CONFIG_FILE if config is not None else None):
                out.append(i)
        except (SyncError, library.LibraryError) as exc:
            add("error", "library", str(exc))
    return out


# --------------------------------------------------------------------------- intake

def add_skill(repo_root: Path, src: Path, *, skill_id: str, category: str, scope: str,
              version: str, authored: bool, url: str | None = None, commit: str | None = None,
              license_id: str | None = None, stacks: list[str] | None = None,
              project_name: str | None = None) -> dict:
    """Copy a skill verbatim into the library as `candidate` with review pending
    (capability 9). Never executes anything from `src`. Atomic: on any validation error the
    library and catalog are left exactly as before."""
    import re
    for label, value in (("id", skill_id), ("category", category)):
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", value or ""):
            raise SyncError(f"invalid {label} {value!r}")
    if not authored and not (url and commit and library.COMMIT_RE.match(commit)):
        raise SyncError("third-party intake needs --url and a full 40-char --commit")
    if src.is_symlink() or not (src / "SKILL.md").is_file():
        raise SyncError(f"{src} must be a directory containing SKILL.md")
    for p in src.rglob("*"):
        if p.is_symlink():
            raise SyncError(f"symlink not allowed in skill content: {p.relative_to(src)}")
    fm, _ = v.split_frontmatter((src / "SKILL.md").read_text(encoding="utf-8"))
    if fm.get("name") != skill_id:
        raise SyncError(f"SKILL.md name {fm.get('name')!r} must equal the id {skill_id!r} (R-03)")
    dest = repo_root / "library" / category / skill_id
    if dest.exists():
        raise SyncError(f"{dest.relative_to(repo_root)} already exists")
    catalog_file = repo_root / "catalog" / "skills.yaml"
    original = catalog_file.read_bytes()
    today = _dt.date.today().isoformat()
    created_category = not dest.parent.exists()
    try:
        shutil.copytree(src, dest, symlinks=True)
        if authored and url and commit and not library.COMMIT_RE.match(commit):
            raise SyncError("--commit for an authored skill must be a full 40-char commit")
        derived = f"derived-from: {url} @ {commit}\n" if authored and url and commit else ""
        source_txt = (f"origin: internal / authored by the owner\n{derived}fetched: {today}\n" if authored else
                      f"origin: {url}\ncommit: {commit}\nlicense: {license_id or 'NOASSERTION'}\n"
                      f"fetched: {today}\n")
        (dest / "SOURCE.txt").write_text(source_txt + "note: copied verbatim; scripts were not executed\n")
        content = v.content_hash(dest)
        description = str(fm.get("description", ""))
        entry = {"id": skill_id, "name": skill_id, "category": category,
                 "path": f"library/{category}/{skill_id}", "scope": scope}
        if scope == "project":
            entry["project"] = project_name
        entry.update({
            "version": version,
            "source": ({"type": "local", "license": license_id, "fetched_at": today, "content_hash": content,
                        **({"url": url, "commit": commit} if url and commit else {})}
                       if authored else
                       {"type": "upstream", "url": url, "commit": commit, "license": license_id,
                        "fetched_at": today, "content_hash": content}),
            "status": "candidate", "review": {"state": "pending"},
            "cost": {"description_chars": len(description),
                     "description_tokens_est": (len(description) + 3) // 4},
            "invocation": "manual" if fm.get("disable-model-invocation") is True else "auto"})
        if stacks:
            entry["stacks"] = stacks
        text = original.decode("utf-8")
        header = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
        data = yaml.load(text, Loader=v._StrictLoader)  # noqa: S506
        data["skills"].append(entry)
        catalog_file.write_text(header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        cat, issues = v.load_catalog(repo_root / "catalog")
        issues += v.check_catalog(cat, "catalog") if cat else []
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise SyncError("catalog invalid after intake: " + "; ".join(map(str, errors)))
        return entry
    except BaseException:
        catalog_file.write_bytes(original)
        shutil.rmtree(dest, ignore_errors=True)
        if created_category and dest.parent.is_dir() and not any(dest.parent.iterdir()):
            dest.parent.rmdir()
        raise


def add_note(project: Path, category: str, text: str) -> None:
    """Append a categorized note or lesson to the project's history (capability 9, 12).
    Locked (F1), recovers any interrupted transaction first so a note is never lost to a
    restore, refuses symlinks (F5), and appends without rewriting the file."""
    import os
    import re
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", category or ""):
        raise SyncError("category must be ASCII letters, digits, and hyphens")
    if len(text) > 20000:
        raise SyncError("note is too long (max 20000 characters)")
    project = project.resolve()
    with lock_mod.project_lock(project):
        txn.recover(project)
        try:
            dest = safe_dest(project, HISTORY_FILE)
        except UnsafePathError as exc:
            raise SyncError(str(exc)) from exc
        try:
            fd = os.open(dest, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
                         | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0), 0o644)  # NONBLOCK: a FIFO must not hang us
        except OSError as exc:
            raise SyncError(f"cannot open {HISTORY_FILE} safely: {exc.strerror}") from exc
        try:
            import stat
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise SyncError(f"{HISTORY_FILE} is not a regular file")
            stamp = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            entry = f"\n## {stamp} - note [{category}]\n\n{text.strip()}\n"
            if os.fstat(fd).st_size == 0:
                entry = (TEMPLATES / "history.md").read_text(encoding="utf-8") + entry
            os.write(fd, entry.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)


def init_config(project: Path, content: str) -> None:
    """Create `.tareq/skills.yaml` only if absent (F5). Locked; never follows a symlink,
    including a dangling one, and never overwrites."""
    import os
    project = project.resolve()
    with lock_mod.project_lock(project):
        try:
            dest = safe_dest(project, CONFIG_FILE)
        except UnsafePathError as exc:
            raise SyncError(str(exc)) from exc
        try:
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                         | getattr(os, "O_CLOEXEC", 0), 0o644)
        except FileExistsError as exc:
            raise SyncError(f"{CONFIG_FILE} already exists; not modified") from exc
        except OSError as exc:
            raise SyncError(f"cannot create {CONFIG_FILE} safely: {exc.strerror}") from exc
        try:
            os.write(fd, content.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
