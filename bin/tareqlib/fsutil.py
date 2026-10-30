"""Filesystem helpers: hashing, glob matching, safe destination paths."""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import tempfile
from pathlib import Path

# Directories never scanned for stack detection.
PRUNE_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
                        "target", ".next", ".gradle", ".idea", ".tareq"})
MAX_SCAN_FILE_BYTES = 1_000_000


class UnsafePathError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_hash(obj) -> str:
    """Hash of a JSON-serializable object with sorted keys and no whitespace."""
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False).encode())


def glob_to_regex(pattern: str) -> re.Pattern:
    """Project-relative glob: `**/` = zero or more dirs, `**` = anything, `*` = within one
    path segment, `?` = one char. Matched against posix relative paths."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def iter_project_files(root: Path):
    """Yield posix relative paths of regular files, pruning vendored/VCS directories and
    never following symlinks."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS
                             and not os.path.islink(os.path.join(dirpath, d)))
        for name in sorted(filenames):
            full = Path(dirpath) / name
            if full.is_symlink() or not full.is_file():
                continue
            yield full.relative_to(root).as_posix()


def safe_dest(root: Path, rel: str) -> Path:
    """Resolve a project-relative path for writing. Rejects absolute paths, `..`, and any
    existing symlink on the way, so a write can never leave the project root."""
    if not rel or rel.startswith("/") or "\\" in rel or ".." in rel.split("/"):
        raise UnsafePathError(f"unsafe path: {rel!r}")
    root = root.resolve()
    current = root
    for part in rel.split("/"):
        current = current / part
        if current.is_symlink():
            raise UnsafePathError(f"refusing to write through symlink: {current.relative_to(root)}")
    return current


def path_state(root: Path, rel: str) -> str | None:
    """Hash of a file, or None when absent. Directories and symlinks are reported as such
    so the plan fingerprint captures them (R-20)."""
    p = root / rel
    if p.is_symlink():
        return "symlink:" + os.readlink(p)
    if p.is_dir():
        return "directory"
    if p.is_file():
        return sha256_file(p)
    return None


def load_json_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


def dump_json(obj: dict) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode()


def real_home() -> Path:
    """The invoking user's home directory from the passwd database, never from $HOME, so an
    environment variable cannot hide personal skills from collision detection (R-13)."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_durable(dest: Path, data: bytes, *, mode: int | None = None, hook=None) -> None:
    """Crash-safe replace: temp file in the same directory, fsync, rename, fsync directory.
    `os.replace` never follows a symlink at `dest`; it replaces the link itself."""
    parent = dest.parent
    if mode is None:
        try:
            mode = dest.stat().st_mode & 0o7777 if dest.is_file() and not dest.is_symlink() else None
        except OSError:
            mode = None
    if mode is None:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".tareq-tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        if hook:
            hook("write:tmp")
        os.replace(tmp, dest)
        fsync_dir(parent)
        if hook:
            hook("write:replaced")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def mkdirs_durable(project: Path, directory: Path) -> list[Path]:
    """Create missing directories below `project` (never through a symlink) and fsync each
    new entry's parent. Returns the directories created, shallowest first."""
    missing = []
    d = directory
    while d != project and not d.exists():
        if d.is_symlink():
            raise UnsafePathError(f"refusing to create through symlink: {d}")
        missing.append(d)
        d = d.parent
    created = []
    for d in reversed(missing):
        d.mkdir()
        created.append(d)
        fsync_dir(d.parent)
    return created
