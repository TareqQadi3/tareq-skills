#!/usr/bin/env python3
"""Validate the tareq-skills catalog, and optionally a client project's
`.tareq/skills.yaml` and `.tareq/skills.lock`.

Validation only (M1): no selection, sync, adapter generation, or rollback.

Usage:
    python3 bin/validate_catalog.py [--catalog DIR] [--project-dir DIR]

Exit code 0 when no errors are found, 1 otherwise. Warnings never fail.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "catalog" / "schema"

# O-03: licenses accepted without an explicit owner exception (SPDX ids).
ACCEPTED_LICENSES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "ISC"})
# O-02: hard maximum of enabled descriptions when a project does not configure one.
DEFAULT_MAX_DESCRIPTIONS = 40
# Categories that may never be reachable from a default pack.
NON_DEFAULT_CATEGORIES = frozenset({"marketing"})
# O-04: conflict priority; lower value wins.
SCOPE_PRIORITY = {"project": 0, "stack": 1, "general": 2}


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning"
    code: str
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity.upper()} [{self.code}] {self.where}: {self.message}"


class DuplicateKeyError(yaml.YAMLError):
    pass


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of silently overwriting."""


def _construct_mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise DuplicateKeyError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass


def file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class UnsafeContentError(ValueError):
    pass


def content_hash(directory: Path) -> str:
    """Deterministic hash of a skill directory: sha256 over sorted
    '<relative posix path>\0<sha256 of bytes>\n' lines. Symlinks and special files are
    rejected so content can never point outside the library."""
    lines = []
    for path in sorted(directory.rglob("*")):
        rel = path.relative_to(directory).as_posix()
        if path.is_symlink():
            raise UnsafeContentError(f"symlink not allowed: {rel}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise UnsafeContentError(f"special file not allowed: {rel}")
        lines.append(f"{rel}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n")
    return "sha256:" + hashlib.sha256("".join(lines).encode()).hexdigest()


def is_safe_relative_glob(pattern: str) -> bool:
    """Project-relative glob: not absolute, no '..' segment, no backslashes, no drive letter."""
    if pattern.startswith(("/", "~")) or "\\" in pattern or re.match(r"^[A-Za-z]:", pattern):
        return False
    return ".." not in pattern.split("/")


# --------------------------------------------------------------------------- schemas

def _load_schemas() -> dict[str, Draft202012Validator]:
    resources = {}
    for path in SCHEMA_DIR.glob("*.schema.json"):
        resources[path.name] = json.loads(path.read_text(encoding="utf-8"))
    registry = Registry().with_resources(
        (name, Resource.from_contents(doc)) for name, doc in resources.items()
    )
    return {
        name.removesuffix(".schema.json"): Draft202012Validator(doc, registry=registry)
        for name, doc in resources.items()
        if name != "common.schema.json"
    }


_VALIDATORS: dict[str, Draft202012Validator] | None = None


def schema_issues(kind: str, data, where: str) -> list[Issue]:
    global _VALIDATORS
    if _VALIDATORS is None:
        _VALIDATORS = _load_schemas()
    issues = []
    for err in sorted(_VALIDATORS[kind].iter_errors(data), key=lambda e: list(e.absolute_path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(Issue("error", "schema", f"{where}#{loc}", err.message))
    return issues


# --------------------------------------------------------------------------- catalog

@dataclass
class Catalog:
    skills: dict
    stacks: dict
    packs: dict
    overlays: dict
    categories: frozenset
    pack_hashes: dict
    overlay_hashes: dict
    root: Path | None = None  # repository root holding library/; None skips content checks


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle as a node path, or None. Edges to unknown nodes are ignored."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    stack: list[str] = []

    def visit(node: str):
        color[node] = GREY
        stack.append(node)
        for nxt in graph.get(node, []):
            if nxt not in color:
                continue
            if color[nxt] == GREY:
                return stack[stack.index(nxt):] + [nxt]
            if color[nxt] == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(graph):
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def _index(items: list[dict], kind: str, where: str, issues: list[Issue]) -> dict:
    out = {}
    for item in items:
        ident = item["id"]
        if ident in out:
            issues.append(Issue("error", "duplicate-id", where, f"duplicate {kind} id '{ident}'"))
            continue
        out[ident] = item
    return out


def expand_pack(pack_id: str, packs: dict, _seen: frozenset = frozenset()) -> set[str]:
    """All skill ids reachable from a pack through `includes` (cycle-safe)."""
    if pack_id in _seen or pack_id not in packs:
        return set()
    pack = packs[pack_id]
    skills = set(pack.get("skills", []))
    for inc in pack.get("includes", []):
        skills |= expand_pack(inc, packs, _seen | {pack_id})
    return skills


def load_catalog(catalog_dir: Path) -> tuple[Catalog | None, list[Issue]]:
    """Load and schema-check every catalog file. Returns (None, issues) on schema errors."""
    issues: list[Issue] = []
    docs = {}
    for name, kind in (("skills.yaml", "skills"), ("stacks.yaml", "stacks")):
        path = catalog_dir / name
        try:
            docs[name] = load_yaml(path)
        except (OSError, yaml.YAMLError) as exc:
            issues.append(Issue("error", "yaml", str(path), str(exc)))
            continue
        issues += schema_issues(kind, docs[name], str(path))

    packs, pack_hashes, overlays, overlay_hashes = [], {}, [], {}
    for sub, kind, bucket, hashes in (("packs", "pack", packs, pack_hashes),
                                      ("overlays", "overlay", overlays, overlay_hashes)):
        for path in sorted((catalog_dir / sub).glob("*.yaml")):
            try:
                doc = load_yaml(path)
            except yaml.YAMLError as exc:
                issues.append(Issue("error", "yaml", str(path), str(exc)))
                continue
            file_issues = schema_issues(kind, doc, str(path))
            issues += file_issues
            if file_issues:
                continue
            key = doc["id"] if kind == "pack" else doc["skill"]
            if path.stem != key:
                issues.append(Issue("error", "file-name", str(path),
                                    f"file name must be '{key}.yaml'"))
            bucket.append((path, doc))
            hashes.setdefault(key, file_hash(path))

    if any(i.severity == "error" for i in issues):
        return None, issues

    where_s, where_t = str(catalog_dir / "skills.yaml"), str(catalog_dir / "stacks.yaml")
    skills = _index(docs["skills.yaml"]["skills"], "skill", where_s, issues)
    stacks = _index(docs["stacks.yaml"]["stacks"], "stack", where_t, issues)
    pack_map = _index([d for _, d in packs], "pack", str(catalog_dir / "packs"), issues)
    overlay_map = {}
    for path, doc in overlays:
        if doc["skill"] in overlay_map:
            issues.append(Issue("error", "duplicate-id", str(path),
                                f"more than one overlay for skill '{doc['skill']}'"))
        overlay_map[doc["skill"]] = doc
    catalog = Catalog(skills, stacks, pack_map, overlay_map,
                      frozenset(docs["skills.yaml"]["categories"]), pack_hashes, overlay_hashes,
                      root=catalog_dir.resolve().parent)
    return catalog, issues


def check_catalog(cat: Catalog, where: str = "catalog") -> list[Issue]:
    """Cross-file consistency rules (run after schema validation)."""
    issues: list[Issue] = []
    err = lambda code, w, msg: issues.append(Issue("error", code, w, msg))  # noqa: E731
    warn = lambda code, w, msg: issues.append(Issue("warning", code, w, msg))  # noqa: E731

    # Skills ---------------------------------------------------------------
    for sid, s in cat.skills.items():
        w = f"{where}/skills/{sid}"
        if s["category"] not in cat.categories:
            err("unknown-category", w, f"category '{s['category']}' is not declared")
        expected_path = f"library/{s['category']}/{sid}"
        if s["path"] != expected_path:
            err("path-mismatch", w, f"path must be '{expected_path}'")
        for field in ("conflicts_with", "replaces", "requires"):
            for ref in s.get(field, []):
                if ref == sid:
                    err("self-reference", w, f"'{field}' references the skill itself")
                elif ref not in cat.skills:
                    err("unknown-skill", w, f"'{field}' references unknown skill '{ref}'")
        for ref in s.get("stacks", []):
            if ref not in cat.stacks:
                err("unknown-stack", w, f"references unknown stack '{ref}'")
        if s["scope"] == "stack" and not s.get("stacks"):
            err("scope-stack-without-stacks", w, "scope 'stack' requires at least one stack")
        for other in s.get("conflicts_with", []):
            o = cat.skills.get(other)
            if o is not None and sid not in o.get("conflicts_with", []):
                err("asymmetric-conflict", w,
                    f"conflicts with '{other}' but '{other}' does not declare the conflict")
        overlap = set(s.get("requires", [])) & set(s.get("conflicts_with", []))
        if overlap:
            err("requires-conflict", w, f"both requires and conflicts with {sorted(overlap)}")

        # Status, review, license (O-03)
        license_id = s["source"]["license"]
        if s["status"] == "active":
            if s["review"]["state"] != "approved":
                err("active-unreviewed", w, "active skill must have review.state 'approved'")
            if license_id not in ACCEPTED_LICENSES and "license_exception" not in s:
                err("license-not-accepted", w,
                    f"license {license_id!r} is not accepted; skill must stay 'candidate' "
                    "unless an owner license_exception is recorded")
            for req in s.get("requires", []):
                r = cat.skills.get(req)
                if r is not None and r["status"] != "active":
                    err("missing-dependency", w, f"requires '{req}' which is '{r['status']}'")
            risk = s.get("risk", {})
            if risk.get("offensive") and not risk.get("isolated_env_only"):
                err("offensive-unrestricted", w,
                    "active offensive skill must set risk.isolated_env_only: true")
        if s["review"]["state"] == "rejected" and s["status"] != "disabled":
            err("rejected-not-disabled", w, "a rejected skill must be 'disabled'")
        for rep in s.get("replaces", []):
            r = cat.skills.get(rep)
            if r is not None and s["status"] == "active" and r["status"] == "active":
                err("replaced-still-active", w, f"replaces '{rep}' but both are active")

    seen_names: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}
    for sid, s in sorted(cat.skills.items()):
        w = f"{where}/skills/{sid}"
        if s["name"] in seen_names:
            err("duplicate-name", w, f"name '{s['name']}' already used by '{seen_names[s['name']]}'")
        seen_names.setdefault(s["name"], sid)
        h = s["source"]["content_hash"]
        if h in seen_hashes:
            warn("duplicate-content", w, f"same content_hash as '{seen_hashes[h]}'")
        seen_hashes.setdefault(h, sid)
        if cat.root is not None:
            directory = cat.root / s["path"]
            if not directory.is_dir() or directory.is_symlink():
                err("missing-content", w, f"skill content not found at '{s['path']}'")
                continue
            try:
                actual = content_hash(directory)
            except UnsafeContentError as exc:
                err("unsafe-content", w, str(exc))
                continue
            if actual != h:
                err("content-hash-mismatch", w,
                    "library content does not match source.content_hash (content changed "
                    "without updating the catalog)")

    cycle = _find_cycle({sid: s.get("requires", []) for sid, s in cat.skills.items()})
    if cycle:
        err("requires-cycle", f"{where}/skills", " -> ".join(cycle))

    # Stacks ---------------------------------------------------------------
    for tid, t in cat.stacks.items():
        w = f"{where}/stacks/{tid}"
        for ref in t.get("implies", []):
            if ref == tid or ref not in cat.stacks:
                err("unknown-stack", w, f"'implies' has invalid stack '{ref}'")
        for rule in t["detect"].get("any", []) + t["detect"].get("all", []):
            glob = rule.get("file") or rule.get("file_contains", {}).get("glob")
            if glob is not None and not is_safe_relative_glob(glob):
                err("unsafe-path", w, f"glob must be project-relative without '..': {glob!r}")
            fc = rule.get("file_contains")
            if fc:
                try:
                    re.compile(fc["pattern"])
                except re.error as exc:
                    err("bad-pattern", w, f"invalid regex {fc['pattern']!r}: {exc}")
    cycle = _find_cycle({tid: t.get("implies", []) for tid, t in cat.stacks.items()})
    if cycle:
        err("implies-cycle", f"{where}/stacks", " -> ".join(cycle))

    # Packs ----------------------------------------------------------------
    for pid, p in cat.packs.items():
        w = f"{where}/packs/{pid}"
        for ref in p.get("skills", []):
            s = cat.skills.get(ref)
            if s is None:
                err("unknown-skill", w, f"references unknown skill '{ref}'")
            elif s["status"] == "disabled":
                err("pack-disabled-skill", w, f"includes disabled skill '{ref}'")
            elif s["status"] == "candidate":
                warn("pack-candidate-skill", w,
                     f"includes candidate skill '{ref}' (not selectable until active)")
        for ref in p.get("includes", []):
            if ref == pid or ref not in cat.packs:
                err("unknown-pack", w, f"'includes' has invalid pack '{ref}'")
        for ref in p.get("stacks", []):
            if ref not in cat.stacks:
                err("unknown-stack", w, f"references unknown stack '{ref}'")
    cycle = _find_cycle({pid: p.get("includes", []) for pid, p in cat.packs.items()})
    if cycle:
        err("pack-cycle", f"{where}/packs", " -> ".join(cycle))
    else:
        for pid, p in cat.packs.items():
            members = expand_pack(pid, cat.packs)
            if p.get("default"):
                bad = sorted(m for m in members
                             if cat.skills.get(m, {}).get("category") in NON_DEFAULT_CATEGORIES)
                if bad:
                    err("default-pack-marketing", f"{where}/packs/{pid}",
                        f"default pack reaches non-default-category skills {bad}")
            for a, b in _conflicting_pairs(members, cat):
                err("pack-conflict", f"{where}/packs/{pid}", f"contains conflicting '{a}' and '{b}'")

    # Overlays -------------------------------------------------------------
    for sid, o in cat.overlays.items():
        if sid not in cat.skills:
            err("unknown-skill", f"{where}/overlays/{sid}", f"overlay targets unknown skill '{sid}'")
        for glob in o["set"].get("paths", []):
            if not is_safe_relative_glob(glob):
                err("unsafe-path", f"{where}/overlays/{sid}",
                    f"paths entry must be project-relative without '..': {glob!r}")

    return issues


def effective_invocation(sid: str, cat: Catalog) -> str:
    """Invocation mode after applying the skill's overlay, if any."""
    return cat.overlays.get(sid, {}).get("set", {}).get("invocation", cat.skills[sid]["invocation"])


def _conflict(a: str, b: str, cat: Catalog) -> bool:
    """True if either side declares the conflict (asymmetric declarations still count)."""
    return (b in cat.skills.get(a, {}).get("conflicts_with", [])
            or a in cat.skills.get(b, {}).get("conflicts_with", []))


def _conflicting_pairs(members, cat: Catalog):
    pairs = set()
    for m in members:
        for other in cat.skills.get(m, {}).get("conflicts_with", []):
            if other in members:
                pairs.add(tuple(sorted((m, other))))
    return sorted(pairs)


# --------------------------------------------------------------------------- project files

def resolve_project_skills(config: dict, cat: Catalog) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """Deterministic expansion of what the configuration declares (packs + include - exclude),
    then O-04 priority: across different scope levels the higher-priority skill wins.
    Not a selection engine. Returns ({skill: [via...]}, [(dropped, winner), ...])."""
    via: dict[str, list[str]] = {}
    for pid in config.get("packs", []):
        for sid in sorted(expand_pack(pid, cat.packs)):
            via.setdefault(sid, []).append(f"pack:{pid}")
    for sid in config.get("include", []):
        via.setdefault(sid, []).append("include")
    for sid in config.get("exclude", []):
        via.pop(sid, None)
    # Highest priority first, then id: a skill is dropped only when it conflicts with an
    # already-kept skill of strictly higher priority. Independent of id spelling.
    dropped = []
    kept: list[str] = []
    for sid in sorted(via, key=lambda x: (SCOPE_PRIORITY[cat.skills[x]["scope"]], x)):
        prio = SCOPE_PRIORITY[cat.skills[sid]["scope"]]
        winner = next((k for k in kept
                       if SCOPE_PRIORITY[cat.skills[k]["scope"]] < prio and _conflict(sid, k, cat)),
                      None)
        if winner is None:
            kept.append(sid)
        else:
            dropped.append((sid, winner))
    for sid, _ in dropped:
        via.pop(sid)
    return via, dropped


def check_project_config(config: dict, cat: Catalog, where: str) -> list[Issue]:
    issues = schema_issues("project-config", config, where)
    if issues:
        return issues
    err = lambda code, msg: issues.append(Issue("error", code, where, msg))  # noqa: E731
    for pid in config.get("packs", []):
        if pid not in cat.packs:
            err("unknown-pack", f"unknown pack '{pid}'")
    for field in ("include", "exclude"):
        for sid in config.get(field, []):
            if sid not in cat.skills:
                err("unknown-skill", f"'{field}' references unknown skill '{sid}'")
    both = set(config.get("include", [])) & set(config.get("exclude", []))
    if both:
        err("include-exclude-overlap", f"skills both included and excluded: {sorted(both)}")
    if issues:
        return issues

    selected, dropped = resolve_project_skills(config, cat)
    for loser, winner in dropped:
        issues.append(Issue("warning", "conflict-priority", where,
                            f"'{loser}' dropped: conflicts with higher-priority '{winner}'"))
    for sid in sorted(selected):
        s = cat.skills[sid]
        if s["status"] != "active":
            err("inactive-skill-selected", f"'{sid}' is '{s['status']}' and cannot be enabled")
        if s["scope"] == "project" and s.get("project") != config["project"]:
            err("foreign-project-skill", f"'{sid}' belongs to project '{s.get('project')}'")
        for req in s.get("requires", []):
            if req not in selected:
                err("missing-dependency", f"'{sid}' requires '{req}' which is not selected")
    for a, b in _conflicting_pairs(set(selected), cat):
        err("unresolved-conflict",
            f"'{a}' and '{b}' conflict at the same priority level; the owner must exclude one")
    limit = config.get("budget", {}).get("max_descriptions", DEFAULT_MAX_DESCRIPTIONS)
    auto = [sid for sid in selected if effective_invocation(sid, cat) == "auto"]
    if len(auto) > limit:
        err("budget-exceeded", f"{len(auto)} auto-invoked descriptions exceed the maximum {limit}")
    return issues


def check_lock(lock: dict, cat: Catalog | None, where: str,
               config: dict | None = None, config_path: Path | None = None) -> list[Issue]:
    issues = schema_issues("lock", lock, where)
    if issues:
        return issues
    err = lambda code, msg: issues.append(Issue("error", code, where, msg))  # noqa: E731
    ids = [e["id"] for e in lock["skills"]]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        err("duplicate-id", f"skill '{dup}' appears more than once")
    if lock["budget"]["used"] > lock["budget"]["max_descriptions"]:
        err("budget-exceeded", "budget.used exceeds budget.max_descriptions")
    for e in lock["skills"]:
        if e["source"]["type"] == "upstream" and not {"url", "commit"} <= e["source"].keys():
            err("unpinned-source", f"'{e['id']}' upstream source needs url and commit")
    if config is not None:
        if lock["project"] != config["project"]:
            err("project-mismatch", "lock project differs from configuration")
        if config_path is not None and lock["config_hash"] != file_hash(config_path):
            err("stale-lock", "config_hash does not match .tareq/skills.yaml")
    if cat is None:
        return issues
    for e in lock["skills"]:
        s = cat.skills.get(e["id"])
        if s is None:
            err("unknown-skill", f"lock references unknown skill '{e['id']}'")
            continue
        if e["content_hash"] != s["source"]["content_hash"]:
            err("hash-mismatch", f"'{e['id']}' content_hash differs from catalog")
        if e["version"] != s["version"]:
            err("version-mismatch", f"'{e['id']}' version differs from catalog")
        if e["license"] != s["source"]["license"]:
            err("license-mismatch", f"'{e['id']}' license differs from catalog")
        if (e["source"]["type"] != s["source"]["type"]
                or e["source"].get("url") != s["source"].get("url")):
            err("source-mismatch", f"'{e['id']}' source type/url differs from catalog")
        if e["source"].get("commit") != s["source"].get("commit"):
            err("commit-mismatch", f"'{e['id']}' source commit differs from catalog")
        if s["status"] != "active":
            err("inactive-skill-selected", f"'{e['id']}' is '{s['status']}' in the catalog")
        overlay_hash = cat.overlay_hashes.get(e["id"])
        if e.get("overlay_hash") != overlay_hash:
            err("overlay-mismatch", f"'{e['id']}' overlay_hash differs from catalog overlay")
    for a, b in _conflicting_pairs(set(ids), cat):
        err("unresolved-conflict", f"lock contains conflicting '{a}' and '{b}'")
    for p in lock["packs"]:
        if cat.pack_hashes.get(p["id"]) != p["hash"]:
            err("pack-mismatch", f"pack '{p['id']}' hash differs from catalog")
    locked_packs = {p["id"] for p in lock["packs"]}
    used_packs = set()
    for e in lock["skills"]:
        for v in e["via"]:
            if v.startswith("pack:"):
                used_packs.add(v[5:])
    for pid in sorted(used_packs):
        used_packs |= _pack_closure(pid, cat.packs)
    for pid in sorted(used_packs - locked_packs):
        err("pack-missing", f"pack '{pid}' is used but not pinned in lock.packs")
    known = [e["id"] for e in lock["skills"] if e["id"] in cat.skills]
    auto = sum(effective_invocation(sid, cat) == "auto" for sid in known)
    if lock["budget"]["used"] != auto:
        err("budget-mismatch", f"budget.used is {lock['budget']['used']}, expected {auto}")
    if config is not None and not any(i.severity == "error" for i in
                                      check_project_config(config, cat, "config")):
        expected, _ = resolve_project_skills(config, cat)
        actual = {e["id"]: e["via"] for e in lock["skills"]}
        if set(actual) != set(expected):
            err("lock-drift", f"lock skills {sorted(actual)} differ from configuration "
                              f"{sorted(expected)}")
        elif any(sorted(actual.get(k, [])) != sorted(expected[k]) for k in expected):
            err("lock-drift", "lock 'via' differs from configuration")
        limit = config.get("budget", {}).get("max_descriptions", DEFAULT_MAX_DESCRIPTIONS)
        if lock["budget"]["max_descriptions"] != limit:
            err("lock-drift", "lock budget.max_descriptions differs from configuration")
        if sorted(lock["targets"]) != sorted(config["targets"]):
            err("lock-drift", "lock targets differ from configuration")
    return issues


def _pack_closure(pack_id: str, packs: dict, _seen: frozenset = frozenset()) -> set[str]:
    """Pack ids reachable through `includes` (cycle-safe), excluding the pack itself."""
    out: set[str] = set()
    for inc in packs.get(pack_id, {}).get("includes", []):
        if inc not in _seen:
            out |= {inc} | _pack_closure(inc, packs, _seen | {pack_id})
    return out


# --------------------------------------------------------------------------- CLI

def validate(catalog_dir: Path, project_dir: Path | None = None) -> list[Issue]:
    cat, issues = load_catalog(catalog_dir)
    if cat is None:
        return issues
    issues += check_catalog(cat, str(catalog_dir))
    if project_dir is not None:
        cfg_path = project_dir / ".tareq" / "skills.yaml"
        lock_path = project_dir / ".tareq" / "skills.lock"
        config = None
        try:
            config = load_yaml(cfg_path)
            issues += check_project_config(config, cat, str(cfg_path))
        except (OSError, yaml.YAMLError) as exc:
            issues.append(Issue("error", "yaml", str(cfg_path), str(exc)))
        if lock_path.exists():
            try:
                lock = load_yaml(lock_path)
                issues += check_lock(lock, cat, str(lock_path), config,
                                     cfg_path if config is not None else None)
            except yaml.YAMLError as exc:
                issues.append(Issue("error", "yaml", str(lock_path), str(exc)))
    return issues


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--catalog", type=Path, default=REPO_ROOT / "catalog")
    ap.add_argument("--project-dir", type=Path, help="client project root containing .tareq/")
    args = ap.parse_args(argv)
    issues = validate(args.catalog, args.project_dir)
    for issue in issues:
        print(issue)
    errors = sum(i.severity == "error" for i in issues)
    print(f"{errors} error(s), {len(issues) - errors} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
