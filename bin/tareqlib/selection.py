"""Propose the smallest suitable skill set for a project (capability 3).

Proposes; never decides between same-priority conflicts (D-16) and never writes an
existing configuration."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import validate_catalog as v  # noqa: E402


def propose(cat: v.Catalog, detected: set[str], tags: set[str] | None = None) -> dict:
    """Packs whose triggering stacks were detected, plus default packs; optional tag filter
    narrows to skills carrying at least one of the tags. Returns a proposal dict."""
    packs = sorted(pid for pid, p in cat.packs.items()
                   if p.get("default") or (set(p.get("stacks", [])) & detected))
    skills: dict[str, list[str]] = {}
    for pid in packs:
        for sid in sorted(v.expand_pack(pid, cat.packs)):
            skills.setdefault(sid, []).append(f"pack:{pid}")
    inactive = sorted(s for s in skills if cat.skills[s]["status"] != "active")
    for s in inactive:
        skills.pop(s)
    if tags:
        skills = {s: via for s, via in skills.items()
                  if set(cat.skills[s].get("tags", [])) & tags}
    # Stack-scoped active skills not in any proposed pack are offered as optional extras.
    optional = sorted(sid for sid, s in cat.skills.items()
                      if sid not in skills and s["status"] == "active" and s["scope"] == "stack"
                      and set(s.get("stacks", [])) & detected)
    if tags:  # narrowed proposal: name the matching skills instead of whole packs
        config = {"packs": [], "include": sorted(skills), "exclude": []}
    else:
        config = {"packs": packs, "include": [], "exclude": inactive}  # candidates cannot be enabled
    selected, dropped = v.resolve_project_skills(config, cat)
    selected = {s: via for s, via in selected.items() if cat.skills[s]["status"] == "active"}
    same_level = v._conflicting_pairs(set(selected), cat)
    return {
        "config": config,
        "skills": selected,
        "dropped_by_priority": dropped,
        "needs_owner_decision": same_level,
        "skipped_inactive": inactive,
        "optional": optional,
    }
