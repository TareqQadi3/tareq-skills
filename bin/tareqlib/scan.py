"""Evaluate catalog/stacks.yaml detection rules against a project (capability 2)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .fsutil import MAX_SCAN_FILE_BYTES, glob_to_regex, iter_project_files


def _read_text(root: Path, rel: str) -> str:
    p = root / rel
    if p.stat().st_size > MAX_SCAN_FILE_BYTES:
        return ""
    return p.read_text(encoding="utf-8", errors="ignore")


class _Project:
    def __init__(self, root: Path):
        self.root = root
        self.files = list(iter_project_files(root))
        self._text: dict[str, str] = {}

    def matching(self, glob: str) -> list[str]:
        rx = glob_to_regex(glob)
        return [f for f in self.files if rx.match(f)]

    def text(self, rel: str) -> str:
        if rel not in self._text:
            self._text[rel] = _read_text(self.root, rel)
        return self._text[rel]


def _npm_has(project: _Project, name: str) -> str | None:
    for rel in project.matching("**/package.json"):
        try:
            data = json.loads(project.text(rel))
        except ValueError:
            continue
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            if isinstance(data.get(section), dict) and name in data[section]:
                return rel
    return None


def _maven_has(project: _Project, name: str) -> str | None:
    group, _, artifact = name.rpartition(":")
    pattern = (re.compile(rf"<groupId>\s*{re.escape(group)}\s*</groupId>\s*"
                          rf"<artifactId>\s*{re.escape(artifact)}\s*</artifactId>")
               if group else re.compile(rf"<artifactId>\s*{re.escape(artifact)}\s*</artifactId>"))
    for rel in project.matching("**/pom.xml"):
        if pattern.search(project.text(rel)):
            return rel
    return None


def _gradle_has(project: _Project, name: str) -> str | None:
    for rel in project.matching("**/build.gradle") + project.matching("**/build.gradle.kts"):
        if name in project.text(rel):
            return rel
    return None


def _pip_has(project: _Project, name: str) -> str | None:
    rx = re.compile(rf"(?im)^\s*[\"']?{re.escape(name)}(\[|[<>=!~;\s\"',]|$)")
    for rel in project.matching("**/requirements*.txt") + project.matching("**/pyproject.toml"):
        if rx.search(project.text(rel)):
            return rel
    return None


_DEPENDENCY = {"npm": _npm_has, "maven": _maven_has, "gradle": _gradle_has, "pip": _pip_has}


def _rule_evidence(project: _Project, rule: dict) -> str | None:
    if "file" in rule:
        hits = project.matching(rule["file"])
        return f"file {hits[0]}" if hits else None
    if "file_contains" in rule:
        rx = re.compile(rule["file_contains"]["pattern"])
        for rel in project.matching(rule["file_contains"]["glob"]):
            if rx.search(project.text(rel)):
                return f"{rel} matches /{rule['file_contains']['pattern']}/"
        return None
    dep = rule["dependency"]
    hit = _DEPENDENCY[dep["ecosystem"]](project, dep["name"])
    return f"{dep['ecosystem']} dependency {dep['name']} in {hit}" if hit else None


def scan(project_root: Path, stacks: dict) -> dict[str, list[str]]:
    """Return {stack_id: [evidence...]} for detected stacks, including those implied."""
    project = _Project(project_root)
    found: dict[str, list[str]] = {}
    for sid, stack in sorted(stacks.items()):
        detect = stack["detect"]
        evidence: list[str] = []
        ok = True
        if "any" in detect:
            hits = [e for e in (_rule_evidence(project, r) for r in detect["any"]) if e]
            ok = bool(hits)
            evidence += hits[:3]
        if ok and "all" in detect:
            hits = [_rule_evidence(project, r) for r in detect["all"]]
            ok = all(hits)
            evidence += [h for h in hits if h]
        if ok:
            found[sid] = evidence
    queue = list(found)
    while queue:
        sid = queue.pop()
        for implied in stacks[sid].get("implies", []):
            if implied not in found:
                found[implied] = [f"implied by {sid}"]
                queue.append(implied)
    return dict(sorted(found.items()))
