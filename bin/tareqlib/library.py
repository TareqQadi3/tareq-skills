"""Fetch the library at an exact commit outside the client repo (D-21, R-14)."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class LibraryError(RuntimeError):
    pass


def cache_root() -> Path:
    base = os.environ.get("TAREQ_CACHE") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "tareq-skills")
    return Path(base)


def _git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if proc.returncode != 0:
        raise LibraryError(f"git {' '.join(args[:2])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout.strip()


def _clone(source: str) -> Path:
    if source.startswith("-"):
        raise LibraryError("invalid library source")
    mirror = cache_root() / "repos" / re.sub(r"[^A-Za-z0-9._-]", "_", source)[-120:]
    if (mirror / "HEAD").exists() or (mirror / ".git").exists():
        _git(["fetch", "--quiet", "--tags", "origin", "+refs/heads/*:refs/remotes/origin/*"], mirror)
    else:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--quiet", "--no-checkout", "--", source, str(mirror)])
    return mirror


def resolve_commit(source: str, ref: str) -> str:
    """Resolve a branch, tag, or commit to a full 40-char commit."""
    if COMMIT_RE.match(ref):
        return ref
    if not REF_RE.match(ref) or ref.startswith("-"):
        raise LibraryError(f"invalid ref {ref!r}")
    mirror = _clone(source)
    for candidate in (f"refs/tags/{ref}", f"refs/remotes/origin/{ref}", ref):
        try:
            return _git(["rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"], mirror)
        except LibraryError:
            continue
    raise LibraryError(f"ref {ref!r} not found in {source}")


def checkout(source: str, commit: str) -> Path:
    """Return a clean worktree of `source` at exactly `commit`, outside any client repo."""
    if not COMMIT_RE.match(commit):
        raise LibraryError("sync must be pinned to a full 40-char commit (R-14)")
    work = cache_root() / "checkouts" / commit
    if not (work / ".git").exists():
        mirror = _clone(source)
        work.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--quiet", "--no-checkout", "--", str(mirror), str(work)])
        _git(["-c", "advice.detachedHead=false", "checkout", "--quiet", "--detach", commit], work)
    head = _git(["rev-parse", "HEAD"], work)
    if head != commit:
        raise LibraryError(f"checkout is at {head}, expected {commit}")
    if _git(["status", "--porcelain", "--untracked-files=all"], work):
        raise LibraryError(f"cached checkout {work} has local changes; delete it and retry")
    return work
