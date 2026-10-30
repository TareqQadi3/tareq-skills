"""Plan and apply a synchronization of a client project (capabilities 5-8, 11).

Safeguards (docs/architecture/adapters.md):
  R-12 never overwrite/delete files or settings the lock does not record as owned
  R-13 name collisions block the plan
  R-14 exact library commit; source hashes verified before copy, outputs after write
  R-15 dry-run summary first; apply needs an Approval bound to that plan's fingerprint
  R-16 disabled skills stay in the catalog; manual files are never touched
  R-18 removal only of owned, unmodified files/keys; modified ones are left and reported
  R-19 caught failures roll back at once; an interrupted run is repaired by journal
       recovery (txn.py) - see docs/architecture/manager.md for the exact guarantee
  R-20 fingerprint = library commit + source hashes + destination state + environment +
       operations
  D-26 apply is refused unless the Approval comes from an accepted channel (approval.py)
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import validate_catalog as v  # noqa: E402

from . import approval as approval_mod, fsutil, lock as lock_mod, txn  # noqa: E402
from .fsutil import UnsafePathError, canonical_hash, path_state, safe_dest, sha256_bytes  # noqa: E402

TOOL_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES = TOOL_ROOT / "templates"

# Ownership rules live in validate_catalog (shared with `validate_catalog.py --project-dir`).
SKILLS_DIR = v.SKILLS_DIR
RULES_FILE = v.RULES_FILE
GITIGNORE_FILE = v.GITIGNORE_FILE
CLAUDE_SETTINGS = v.CLAUDE_SETTINGS
OPENCODE_SETTINGS = v.OPENCODE_SETTINGS
LOCK_FILE = v.LOCK_REL
HISTORY_FILE = v.HISTORY_REL
CONFIG_FILE = ".tareq/skills.yaml"
OVERLAY_FRONTMATTER = ("description", "when_to_use", "paths")
OPENCODE_DESCRIPTION_MAX = 1024
_MISSING = object()


class SyncError(RuntimeError):
    pass


# --------------------------------------------------------------------------- desired state

@dataclass
class Desired:
    files: dict[str, bytes] = field(default_factory=dict)
    skills: list[dict] = field(default_factory=list)          # lock `skills` entries
    settings: dict[str, dict] = field(default_factory=dict)   # file -> {"keys": {tuple: v}, "items": set}
    lock_base: dict = field(default_factory=dict)             # lock fields except volatile ones
    source_hashes: dict[str, str] = field(default_factory=dict)
    catalog: v.Catalog | None = None


def mapping_hash(files: dict[str, bytes]) -> str:
    """Same algorithm as validate_catalog.content_hash, over an in-memory mapping."""
    return v.mapping_hash_of({rel: sha256_bytes(data) for rel, data in files.items()})


def _skill_files(src: Path) -> dict[str, bytes]:
    out = {}
    for path in sorted(src.rglob("*")):
        if path.is_symlink():
            raise SyncError(f"symlink in library content: {path}")
        if path.is_file():
            out[path.relative_to(src).as_posix()] = path.read_bytes()
    return out


def _apply_frontmatter_overlay(text: str, overlay_set: dict) -> str:
    fm, body = v.split_frontmatter(text)
    for key in OVERLAY_FRONTMATTER:
        if key in overlay_set:
            fm[key] = overlay_set[key]
    dumped = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
    return f"---\n{dumped}---\n{body}"


def _render(template: str, **values) -> bytes:
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text.encode()


def load_library_catalog(checkout: Path) -> v.Catalog:
    cat, issues = v.load_catalog(checkout / "catalog")
    if cat is None:
        raise SyncError("library catalog failed schema validation at this commit:\n  "
                        + "\n  ".join(map(str, issues)))
    errors = [i for i in issues + v.check_catalog(cat, "library") if i.severity == "error"]
    if errors:
        raise SyncError("library catalog is invalid at this commit (includes content-hash "
                        "checks, R-14):\n  " + "\n  ".join(map(str, errors)))
    return cat


def build_desired(*, checkout: Path, commit: str, repo: str, ref: str | None, project: str,
                  resolved: dict[str, list[str]], targets: list[str], max_descriptions: int,
                  config_hash: str, blocks: list[str], warnings: list[str],
                  pack_hashes: dict[str, str] | None = None) -> Desired:
    cat = load_library_catalog(checkout)
    d = Desired(catalog=cat)
    manual: list[str] = []
    for sid in sorted(resolved):
        s = cat.skills.get(sid)
        if s is None:
            blocks.append(f"skill '{sid}' is not in the library catalog at {commit[:12]}")
            continue
        if s["status"] != "active":
            blocks.append(f"skill '{sid}' is '{s['status']}' and cannot be synchronized")
            continue
        src = checkout / s["path"]
        actual = v.content_hash(src)
        if actual != s["source"]["content_hash"]:  # R-14 (also enforced by catalog check)
            blocks.append(f"source hash mismatch for '{sid}'")
            continue
        files = _skill_files(src)
        overlay = cat.overlays.get(sid, {}).get("set", {})
        if any(k in overlay for k in OVERLAY_FRONTMATTER):  # R-07
            files["SKILL.md"] = _apply_frontmatter_overlay(
                files["SKILL.md"].decode("utf-8"), overlay).encode()
        fm, _ = v.split_frontmatter(files["SKILL.md"].decode("utf-8"))
        if fm.get("name") != sid:  # R-03
            blocks.append(f"'{sid}': SKILL.md name must equal the id")
        description = str(fm.get("description", ""))
        if "opencode" in targets and not 1 <= len(description) <= OPENCODE_DESCRIPTION_MAX:  # R-04
            blocks.append(f"'{sid}': description is {len(description)} chars; OpenCode needs 1-1024")
        for rel, data in files.items():
            d.files[f"{SKILLS_DIR}/{sid}/{rel}"] = data
        if v.effective_invocation(sid, cat) == "manual":
            manual.append(sid)
        d.source_hashes[sid] = actual
        entry = {"id": sid, "version": s["version"],
                 "source": {k: s["source"][k] for k in ("type", "url", "commit") if k in s["source"]},
                 "content_hash": actual, "license": s["source"]["license"],
                 "via": resolved[sid], "output_hash": mapping_hash(files)}
        if sid in cat.overlay_hashes:
            entry["overlay_hash"] = cat.overlay_hashes[sid]
        d.skills.append(entry)

    # Budget (D-14, R-06): Claude lists auto skills; OpenCode lists every permitted skill.
    claude_count = len(d.skills) - len(manual)
    opencode_count = len(d.skills)
    if "claude-code" in targets and claude_count > max_descriptions:
        blocks.append(f"Claude Code budget: {claude_count} listed descriptions > {max_descriptions}")
    if "opencode" in targets and opencode_count > max_descriptions:
        blocks.append(f"OpenCode budget: {opencode_count} listed skills > {max_descriptions} "
                      "(manual skills stay listed in OpenCode)")

    # Invocation control without editing SKILL.md (R-05).
    if "claude-code" in targets:
        d.settings[CLAUDE_SETTINGS] = {"keys": {("skillOverrides", sid): "user-invocable-only"
                                                for sid in manual}, "items": set()}
    if "opencode" in targets:
        d.settings[OPENCODE_SETTINGS] = {"keys": {("permission", "skill", sid): "ask" for sid in manual},
                                         "items": {(("instructions",), RULES_FILE)}}

    # Project files: short always-loaded rules file + on-demand register per category.
    by_category: dict[str, list[dict]] = {}
    for e in d.skills:
        by_category.setdefault(cat.skills[e["id"]]["category"], []).append(e)
    register_links = []
    for category, entries in sorted(by_category.items()):
        rows = []
        for e in entries:
            src = e["source"]
            link = (f"{src['url']} @ `{src['commit'][:12]}`" if src["type"] == "upstream"
                    else "internal / authored")
            mode = "manual" if e["id"] in manual else "auto"
            rows.append(f"| `{e['id']}` | {e['version']} | {link} | {e['license'] or 'n/a'} | {mode} |")
        rel = f".tareq/SKILLS-{category}.md"
        d.files[rel] = _render("SKILLS-category.md", category=category, commit=commit,
                               rows="\n".join(rows))
        register_links.append(f"`{rel}`")
    d.files[RULES_FILE] = _render("tareq-skills.rules.md", commit=commit[:12],
                                  registers=", ".join(register_links) or "none")
    d.files[GITIGNORE_FILE] = _render("tareq-gitignore")

    used_packs = set()
    for e in d.skills:
        for via in e["via"]:
            if via.startswith("pack:"):
                used_packs.add(via[5:])
    for pid in sorted(used_packs):
        used_packs |= v._pack_closure(pid, cat.packs)
    hashes = pack_hashes if pack_hashes is not None else cat.pack_hashes
    d.lock_base = {
        "lock_version": 2, "project": project,
        "catalog": {"repo": repo, "commit": commit, **({"ref": ref} if ref else {})},
        "config_hash": config_hash,
        "budget": {"max_descriptions": max_descriptions,
                   "used": sum(v.effective_invocation(e["id"], cat) == "auto" for e in d.skills)},
        "targets": sorted(targets),
        "packs": [{"id": p, "hash": hashes[p]} for p in sorted(used_packs) if p in hashes],
        "skills": d.skills,
    }
    return d


# --------------------------------------------------------------------------- planning

@dataclass
class Plan:
    fingerprint: str
    operations: list[dict]
    blocks: list[str]
    warnings: list[str]
    released: list[str]
    destination: dict[str, str | None]
    desired: Desired | None
    summary: str = ""

    @property
    def ok(self) -> bool:
        return not self.blocks


def read_lock(project: Path, blocks: list[str]) -> dict | None:
    path = project / LOCK_FILE
    if not path.exists():
        return None
    try:
        lock = v.load_yaml(path)
    except (OSError, yaml.YAMLError) as exc:
        blocks.append(f"{LOCK_FILE} is unreadable: {exc}")
        return None
    issues = v.schema_issues("lock", lock, LOCK_FILE)
    if issues:
        blocks.append(f"{LOCK_FILE} is not a valid version-2 lock; ownership cannot be "
                      f"established: {issues[0].message}")
        return None
    forged = v.check_lock_ownership(lock, LOCK_FILE)
    if forged:  # F4: a lock may only claim what tareq-skills itself generates
        blocks += [f"forged or corrupt ownership claim in {LOCK_FILE}: {i.message} (R-12)"
                   for i in forged]
        return None
    return lock


def _get(obj: dict, key: tuple):
    for part in key:
        if not isinstance(obj, dict) or part not in obj:
            return _MISSING
        obj = obj[part]
    return obj


def _set(obj: dict, key: tuple, value) -> None:
    for part in key[:-1]:
        obj = obj.setdefault(part, {})
        if not isinstance(obj, dict):
            raise SyncError(f"cannot set {'.'.join(key)}: '{part}' is not an object")
    obj[key[-1]] = value


def _remove(obj: dict, key: tuple) -> None:
    parents = []
    for part in key[:-1]:
        parents.append((obj, part))
        obj = obj[part]
    del obj[key[-1]]
    for parent, part in reversed(parents):  # drop containers this removal emptied
        if parent[part] == {}:
            del parent[part]


def _collisions(project: Path, home: Path, skill_ids: list[str], owned: dict[str, str],
                blocks: list[str], warnings: list[str], targets: list[str]) -> list[str]:
    """R-09 / R-13: any collision blocks the plan. Returns the sorted list of collision
    probes found, which is part of the plan fingerprint (R-20)."""
    probe: list[str] = []
    personal = [home / ".claude/skills", home / ".config/opencode/skills", home / ".agents/skills"]
    project_other = [project / ".opencode/skills", project / ".agents/skills"]
    for sid in skill_ids:
        for base in personal:
            if (base / sid).exists() or (base / sid).is_symlink():
                probe.append(f"personal:{base.relative_to(home).as_posix()}/{sid}")
                blocks.append(f"collision: personal skill '{base / sid}' has the same name as "
                              f"'{sid}' (it would shadow or duplicate the project copy)")
        for base in project_other:
            if (base / sid).exists():
                probe.append(f"project:{(base / sid).relative_to(project).as_posix()}")
                blocks.append(f"collision: '{(base / sid).relative_to(project)}' duplicates '{sid}' "
                              "(OpenCode requires unique names)")
    skills_root = project / SKILLS_DIR
    if skills_root.is_dir():
        owned_dirs = {p.split("/")[2] for p in owned if p.startswith(SKILLS_DIR + "/")}
        for entry in sorted(skills_root.iterdir()):
            if entry.name in owned_dirs or not (entry / "SKILL.md").is_file():
                continue
            try:
                fm, _ = v.split_frontmatter((entry / "SKILL.md").read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, v.FrontmatterError):
                continue
            if fm.get("name") in skill_ids and fm.get("name") != entry.name:
                probe.append(f"manual:{entry.name}={fm.get('name')}")
                blocks.append(f"collision: manual skill '{SKILLS_DIR}/{entry.name}' declares "
                              f"name '{fm.get('name')}'")
    if "opencode" in targets:
        for var in ("OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"):
            if os.environ.get(var):
                probe.append(f"env:{var}")
                warnings.append(f"{var} is set: OpenCode will not read {SKILLS_DIR}")
    return sorted(probe)


def plan_sync(project: Path, desired: Desired, *, home: Path, library_source: str,
              blocks: list[str], warnings: list[str], adopt: set[str] = frozenset(),
              approve_overwrite: set[str] = frozenset(), rollback_from: str | None = None,
              verify_lock=None) -> Plan:
    """`verify_lock(lock) -> list[str]` corroborates the existing lock's skill files against
    the library at the lock's commit (F4); problems become blocks."""
    project = project.resolve()
    if txn.pending(project):
        blocks.append("an interrupted sync/rollback left a transaction in .tareq/.txn; "
                      "run `tareq recover` first")
    lock = read_lock(project, blocks)
    if lock is not None and verify_lock is not None:
        problems = verify_lock(lock)
        if problems:
            blocks += [f"lock ownership not corroborated by the library: {p} (R-12)" for p in problems]
            lock = None
    owned: dict[str, str] = {g["path"]: g["hash"] for g in (lock or {}).get("generated", [])}
    for rel in sorted(owned):
        try:
            safe_dest(project, rel)
        except UnsafePathError as exc:
            blocks.append(f"{exc} (R-12)")
            owned.pop(rel)
    owned_settings = {s["file"]: s for s in (lock or {}).get("settings", [])}
    ops: list[dict] = []
    released: list[str] = []
    destination: dict[str, str | None] = {}
    skill_ids = [e["id"] for e in desired.skills]
    targets = desired.lock_base.get("targets", [])
    environment = _collisions(project, home, skill_ids, owned, blocks, warnings, targets)

    def state(rel: str):
        if rel not in destination:
            destination[rel] = path_state(project, rel)
        return destination[rel]

    # Files -----------------------------------------------------------------
    for rel, data in sorted(desired.files.items()):
        try:
            safe_dest(project, rel)
        except UnsafePathError as exc:
            blocks.append(str(exc))
            continue
        new = sha256_bytes(data)
        cur = state(rel)
        skill = rel.split("/")[2] if rel.startswith(SKILLS_DIR + "/") else None
        if cur is None:
            ops.append({"op": "write", "path": rel, "hash": new})
        elif cur in ("directory",) or cur.startswith("symlink:"):
            blocks.append(f"'{rel}' exists as a {cur.split(':')[0]}; refusing to replace it")
        elif rel in owned:
            if cur != owned[rel]:
                blocks.append(f"'{rel}' was generated by tareq-skills but edited by hand; "
                              "restore or remove it manually (R-12)")
            elif cur != new:
                ops.append({"op": "write", "path": rel, "hash": new})
        elif skill and skill in adopt and cur == new:
            ops.append({"op": "adopt", "path": rel, "hash": new})  # identical content, no write
        elif skill and skill in approve_overwrite:
            ops.append({"op": "write", "path": rel, "hash": new, "overwrite_unowned": True})
        else:
            blocks.append(f"'{rel}' exists and is not managed by tareq-skills (R-12); "
                          + ("use --adopt only if identical, or " if skill else "")
                          + "resolve it manually or approve the overwrite explicitly")

    # Unmanaged extra files inside generated skill directories would change their content.
    for sid in skill_ids:
        base = project / SKILLS_DIR / sid
        if base.is_dir() and not base.is_symlink():
            for path in sorted(base.rglob("*")):
                rel = path.relative_to(project).as_posix()
                if (path.is_file() or path.is_symlink()) and rel not in desired.files and rel not in owned:
                    if sid in approve_overwrite:
                        ops.append({"op": "delete", "path": rel, "hash": state(rel),
                                    "overwrite_unowned": True})
                    else:
                        blocks.append(f"'{rel}' is an unmanaged file inside skill '{sid}' (R-12)")
        elif base.is_symlink():
            blocks.append(f"'{SKILLS_DIR}/{sid}' is a symlink; refusing to write through it")

    # Owned files no longer desired: remove only if unmodified (R-16, R-18).
    for rel, recorded in sorted(owned.items()):
        if rel in desired.files:
            continue
        cur = state(rel)
        if cur == recorded:
            ops.append({"op": "delete", "path": rel, "hash": recorded})
        elif cur is None:
            released.append(f"'{rel}' was already removed")
        else:
            released.append(f"'{rel}' was edited by hand; left untouched and no longer managed")

    # Settings files (R-05, R-08, R-12, R-18) -------------------------------
    new_settings: list[dict] = []
    for file in sorted(set(desired.settings) | set(owned_settings)):
        want = desired.settings.get(file, {"keys": {}, "items": set()})
        prev = owned_settings.get(file, {"created": False, "keys": [], "list_items": []})
        prev_keys = {tuple(k["key"]): k["value"] for k in prev["keys"]}
        prev_items = {(tuple(i["key"]), i["value"]) for i in prev["list_items"]}
        cur_state = state(file)
        try:
            current = fsutil.load_json_object(project / file) if cur_state else {}
        except (ValueError, OSError) as exc:
            blocks.append(f"'{file}' is not valid JSON; refusing to modify it: {exc}")
            continue
        result = yaml.safe_load(yaml.safe_dump(current))  # deep copy
        kept_keys: dict[tuple, object] = {}
        kept_items: set = set()
        changes: list[str] = []
        for key, value in sorted(want["keys"].items()):
            cur = _get(current, key)
            if key in prev_keys:
                if cur == value:
                    pass
                elif cur == prev_keys[key] or cur is _MISSING:
                    _set(result, key, value)
                    changes.append(f"set {'.'.join(key)}")
                else:
                    blocks.append(f"'{file}' key {'.'.join(key)} was changed by hand (R-12)")
                    continue
            elif cur is _MISSING:
                _set(result, key, value)
                changes.append(f"set {'.'.join(key)}")
            else:
                blocks.append(f"'{file}' key {'.'.join(key)} exists and is not managed by "
                              "tareq-skills (R-12)")
                continue
            kept_keys[key] = value
        for key, value in sorted(prev_keys.items()):
            if key in want["keys"]:
                continue
            cur = _get(current, key)
            if cur == value:
                _remove(result, key)
                changes.append(f"remove {'.'.join(key)}")
            elif cur is not _MISSING:
                released.append(f"'{file}' key {'.'.join(key)} was changed by hand; left untouched")
        for key, value in sorted(want["items"]):
            lst = _get(current, key)
            if lst is _MISSING:
                _set(result, key, [value])
                changes.append(f"add {value} to {'.'.join(key)}")
            elif not isinstance(lst, list):
                blocks.append(f"'{file}' {'.'.join(key)} is not a list")
                continue
            elif value in lst and (key, value) not in prev_items:
                blocks.append(f"'{file}' {'.'.join(key)} already lists '{value}' (not managed; R-12)")
                continue
            elif value not in lst:
                _get(result, key).append(value)
                changes.append(f"add {value} to {'.'.join(key)}")
            kept_items.add((key, value))
        for key, value in sorted(prev_items):
            if (key, value) in want["items"]:
                continue
            lst = _get(result, key)
            if isinstance(lst, list) and value in lst:
                lst.remove(value)
                if not lst:
                    _remove(result, key)
                changes.append(f"remove {value} from {'.'.join(key)}")
        created = prev["created"] or (cur_state is None and bool(kept_keys or kept_items))
        if result == current and cur_state is not None:
            pass
        elif cur_state is None and not (kept_keys or kept_items):
            pass
        elif result == {} and created and prev.get("file_hash") == cur_state:
            ops.append({"op": "delete", "path": file, "hash": cur_state, "settings": changes})
        else:
            data = fsutil.dump_json(result)
            ops.append({"op": "write", "path": file, "hash": sha256_bytes(data), "settings": changes})
            desired.files.setdefault(file, data)
        if kept_keys or kept_items:
            final = desired.files.get(file)
            wrote = any(o["path"] == file and o["op"] == "write" for o in ops)
            file_hash = sha256_bytes(final) if wrote and final is not None else (
                prev.get("file_hash") or cur_state)  # keep "as we last wrote it" if unchanged
            new_settings.append({"file": file, "created": created, "file_hash": file_hash,
                                 "keys": [{"key": list(k), "value": val} for k, val in sorted(kept_keys.items())],
                                 "list_items": [{"key": list(k), "value": val} for k, val in sorted(kept_items)]})
    desired.lock_base["settings"] = new_settings

    state(LOCK_FILE)
    state(HISTORY_FILE)
    ops.append({"op": "write_lock", "path": LOCK_FILE})
    ops.append({"op": "append_history", "path": HISTORY_FILE})
    if rollback_from:
        desired.lock_base["rollback"] = {"from_rev": rollback_from}

    fingerprint = canonical_hash({
        "library": {"source": library_source, "commit": desired.lock_base["catalog"]["commit"]},
        "config_hash": desired.lock_base["config_hash"],
        "source_hashes": desired.source_hashes,
        "destination": destination,
        "environment": environment,
        "operations": ops,
        "lock": {k: val for k, val in desired.lock_base.items()},
    })
    plan = Plan(fingerprint, ops, blocks, warnings, released, destination, desired)
    plan.summary = summarize(plan, lock)
    return plan


def summarize(plan: Plan, previous_lock: dict | None) -> str:
    lb = plan.desired.lock_base if plan.desired else {}
    before = {s["id"]: s for s in (previous_lock or {}).get("skills", [])}
    after = {s["id"]: s for s in lb.get("skills", [])}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    updated = sorted(s for s in set(after) & set(before)
                     if after[s]["output_hash"] != before[s].get("output_hash"))
    lines = [f"Plan fingerprint: {plan.fingerprint}",
             f"Library commit:   {lb.get('catalog', {}).get('commit', '?')}"]
    if lb.get("rollback"):
        lines.append(f"Rollback to:      {lb['rollback']['from_rev']} (.tareq/skills.yaml is not modified)")
    lines += [f"Skills added:     {', '.join(added) or '-'}",
              f"Skills updated:   {', '.join(updated) or '-'}",
              f"Skills removed:   {', '.join(removed) or '-'}",
              f"Budget:           {(previous_lock or {}).get('budget', {}).get('used', 0)} -> "
              f"{lb.get('budget', {}).get('used', 0)} of {lb.get('budget', {}).get('max_descriptions', '?')}"]
    counts: dict[str, int] = {}
    for op in plan.operations:
        counts[op["op"]] = counts.get(op["op"], 0) + 1
    lines.append("Operations:       " + ", ".join(f"{k}={n}" for k, n in sorted(counts.items())))
    for op in plan.operations:
        if op.get("overwrite_unowned"):
            lines.append(f"  OVERWRITE (approved): {op['op']} {op['path']}")
        for change in op.get("settings", []):
            lines.append(f"  {op['path']}: {change}")
    if "opencode" in lb.get("targets", []):
        lines.append("OpenCode:         output follows documented behavior only; NOT TESTED (R-17)")
    for w in plan.warnings:
        lines.append(f"WARNING: {w}")
    for r in plan.released:
        lines.append(f"LEFT UNTOUCHED: {r}")
    for b in plan.blocks:
        lines.append(f"BLOCKED: {b}")
    lines.append("Status:           " + ("ready; apply requires this fingerprint" if plan.ok
                                         else "blocked; nothing can be applied"))
    return "\n".join(lines)


# --------------------------------------------------------------------------- apply (journaled)

def touched_paths(plan: Plan) -> list[str]:
    """Every path an apply may modify: write/delete operations plus the lock and history."""
    paths = {op["path"] for op in plan.operations if op["op"] in ("write", "delete")}
    paths.update({LOCK_FILE, HISTORY_FILE})
    return sorted(paths)


def apply_plan(project: Path, plan: Plan, approval: approval_mod.Approval, *,
               fault_hook=None, checkout_catalog: v.Catalog | None = None,
               config: dict | None = None) -> dict:
    """Apply `plan` only with an Approval from an accepted channel bound to exactly this
    plan's fingerprint (R-15, R-20, D-26), while holding the project lock (F1).

    Failures that Python can catch roll back immediately from the journal. A process kill or
    machine interruption leaves the journal on disk and the next locked command (or
    `tareq recover`) restores the exact pre-sync state (F2, R-19)."""
    project = project.resolve()
    lock_mod.assert_held(project)
    approval_mod.require(approval, plan.fingerprint)
    if not plan.ok:
        raise SyncError("plan is blocked:\n  " + "\n  ".join(plan.blocks))
    tx = txn.Transaction(project, touched_paths(plan), plan.fingerprint, fault_hook)
    try:
        tx.begin(plan.destination)
        for index, op in enumerate(plan.operations):
            tx.step(f"op:{index}:before")
            _execute(project, op, plan, tx, approval)
            tx.step(f"op:{index}:after")
        tx.step("verify:before")
        _verify_after_write(project, plan, checkout_catalog, config)
        tx.step("verify:after")
        tx.commit()
    except BaseException as exc:
        outcome = tx.abort()
        if outcome == "committed":  # the failure struck after the durable commit point
            return plan.desired.lock_base
        if not isinstance(exc, Exception):  # KeyboardInterrupt/SystemExit: restored, then propagate
            raise
        raise SyncError("sync failed and the project was restored to its exact pre-sync "
                        f"state: {exc}") from exc
    return plan.desired.lock_base


def _execute(project: Path, op: dict, plan: Plan, tx: txn.Transaction,
             approval: approval_mod.Approval) -> None:
    kind = op["op"]
    if kind == "write":
        tx.write(op["path"], plan.desired.files[op["path"]])
    elif kind == "delete":
        if path_state(project, op["path"]) != op["hash"]:
            raise SyncError(f"'{op['path']}' changed after planning")
        tx.delete(op["path"])
    elif kind == "adopt":
        if path_state(project, op["path"]) != op["hash"]:
            raise SyncError(f"'{op['path']}' changed after planning")
    elif kind == "write_lock":
        lock = dict(plan.desired.lock_base)
        lock["generated_at"] = _now()
        lock["plan_fingerprint"] = plan.fingerprint
        lock["approval"] = {"channel": approval.channel, "approver": approval.approver,
                            "at": approval.at}
        lock["generated"] = [{"path": rel, "hash": sha256_bytes(data)}
                             for rel, data in sorted(plan.desired.files.items())
                             if rel not in v.SETTINGS_FILES]
        order = ["lock_version", "generated_at", "project", "catalog", "config_hash", "budget",
                 "targets", "packs", "skills", "generated", "settings", "plan_fingerprint",
                 "approval", "rollback"]
        lock = {k: lock[k] for k in order if k in lock}
        header = "# Generated by tareq-skills. Do not edit; use the tareq-skill workflow.\n"
        tx.write(LOCK_FILE, (header + yaml.safe_dump(lock, sort_keys=False,
                                                     allow_unicode=True)).encode())
    elif kind == "append_history":
        path = project / HISTORY_FILE
        existing = path.read_bytes() if path.is_file() else (TEMPLATES / "history.md").read_bytes()
        lb = plan.desired.lock_base
        title = "rollback" if lb.get("rollback") else "sync"
        entry = (f"\n## {_now()} - {title}\n\n"
                 f"- Library commit: `{lb['catalog']['commit']}`\n"
                 f"- Plan fingerprint: `{plan.fingerprint}`\n"
                 f"- Approved by: {approval.approver} via {approval.channel} at {approval.at}\n"
                 f"- Skills: {', '.join(e['id'] for e in lb['skills']) or 'none'}\n")
        if lb.get("rollback"):
            entry += f"- Rolled back to: `{lb['rollback']['from_rev']}`\n"
        for r in plan.released:
            entry += f"- Left untouched: {r}\n"
        tx.write(HISTORY_FILE, existing + entry.encode())
    else:
        raise SyncError(f"unknown operation {kind}")


def _verify_after_write(project: Path, plan: Plan, cat: v.Catalog | None, config: dict | None) -> None:
    """R-14: verify every written output, each skill directory as a whole, and the lock."""
    for rel, data in plan.desired.files.items():  # the whole desired state, not only writes
        if path_state(project, rel) != sha256_bytes(data):
            raise SyncError(f"post-write hash mismatch for '{rel}'")
    for op in plan.operations:
        if op["op"] == "delete" and path_state(project, op["path"]) is not None:
            raise SyncError(f"'{op['path']}' still exists after delete")
    for e in plan.desired.skills:
        if v.content_hash(project / SKILLS_DIR / e["id"]) != e["output_hash"]:
            raise SyncError(f"skill directory '{e['id']}' does not match its expected output hash")
    lock = v.load_yaml(project / LOCK_FILE)
    issues = v.schema_issues("lock", lock, LOCK_FILE)
    if not issues:
        issues = v.check_lock_ownership(lock, LOCK_FILE)
    if cat is not None and not issues:
        issues = v.check_lock(lock, cat, LOCK_FILE, config,
                              project / CONFIG_FILE if config is not None else None)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise SyncError("written lock failed validation: " + "; ".join(map(str, errors)))


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
