"""Durable transaction journal with crash recovery (F2, R-19).

Protocol (all steps fsync'd; the only commit point is the durable COMMITTED marker):
  1. `.tareq/.txn/` is created and every touched file is backed up under `files/`.
  2. `journal.json` is written atomically. Its existence means "backups complete"; no
     project file is modified before it is durable.
  3. Operations run; each file write is temp + fsync + rename + fsync(dir).
  4. Post-write verification.
  5. `COMMITTED` marker is written durably; then the transaction directory is removed.

Recovery (any locked command, `tareq recover`):
  - no journal            -> nothing was modified: discard the directory
  - journal + COMMITTED   -> the transaction completed: discard the directory
  - journal, no COMMITTED -> restore every touched file from its backup, remove directories the
                             transaction created, delete leftover temp files, re-verify that
                             every path equals its recorded pre-state, then discard.
Recovery is idempotent, so a crash during recovery is repaired by running it again.

Guarantee: after any process termination (including SIGKILL) at any step, the next locked
command leaves the project either exactly in its pre-sync state or fully applied. Power-loss
durability relies on fsync ordering and is NOT TESTED (cannot be simulated here).
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import validate_catalog as v  # noqa: E402

from .fsutil import (UnsafePathError, fsync_dir, mkdirs_durable, path_state, safe_dest,  # noqa: E402
                     sha256_bytes, write_durable)

TXN_REL = ".tareq/.txn"
JOURNAL = "journal.json"
COMMITTED = "COMMITTED"
JOURNAL_VERSION = 1


class TransactionError(RuntimeError):
    pass


def pending(project: Path) -> bool:
    txn = project / TXN_REL
    return txn.is_symlink() or txn.exists()


def _hook(hook, name: str) -> None:
    if hook:
        hook(name)


def _check_path(project: Path, rel: str) -> Path:
    if not v.is_touchable_path(rel):
        raise TransactionError(f"'{rel}' is not a path tareq-skills may modify")
    try:
        return safe_dest(project, rel)
    except UnsafePathError as exc:
        raise TransactionError(str(exc)) from exc


class Transaction:
    def __init__(self, project: Path, paths: list[str], fingerprint: str, hook=None):
        self.project = project
        self.paths = sorted(paths)
        self.fingerprint = fingerprint
        self.hook = hook
        self.txn = project / TXN_REL
        self.created_dirs: list[Path] = []

    def step(self, name: str) -> None:
        _hook(self.hook, name)

    def begin(self, expected: dict[str, str | None]) -> None:
        """Snapshot and make the journal durable. Verifies the destination still matches the
        approved plan (closes the plan-to-write window for non-tareq actors)."""
        if pending(self.project):
            raise TransactionError("an interrupted transaction exists; run `tareq recover`")
        for rel, state in expected.items():
            if path_state(self.project, rel) != state:
                raise TransactionError(f"'{rel}' changed after planning; create a new plan")
        self.step("txn:begin")
        self.txn.mkdir()
        fsync_dir(self.txn.parent)
        entries = []
        for i, rel in enumerate(self.paths):
            dest = _check_path(self.project, rel)
            before = path_state(self.project, rel)
            if before is None:
                entries.append({"path": rel, "before": None, "backup": False})
            elif before.startswith("sha256:"):
                data = dest.read_bytes()
                backup = self.txn / "files" / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                write_durable(backup, data)
                entries.append({"path": rel, "before": before, "backup": True,
                                "mode": dest.stat().st_mode & 0o7777})
            else:
                raise TransactionError(f"'{rel}' is a {before.split(':')[0]}; refusing to touch it")
            self.step(f"txn:backup:{i}")
        missing = []
        for rel in self.paths:
            parent = (self.project / rel).parent
            while parent != self.project and not parent.exists():
                missing.append(parent.relative_to(self.project).as_posix())
                parent = parent.parent
        dirs = sorted(set(missing), key=lambda d: (d.count("/"), d))
        journal = {"version": JOURNAL_VERSION, "fingerprint": self.fingerprint,
                   "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pid": os.getpid(),
                   "entries": entries, "created_dirs": dirs}
        write_durable(self.txn / JOURNAL, (json.dumps(journal, indent=1) + "\n").encode())
        fsync_dir(self.txn)
        self.step("txn:prepared")

    def write(self, rel: str, data: bytes) -> None:
        dest = _check_path(self.project, rel)
        mkdirs_durable(self.project, dest.parent)
        write_durable(dest, data, hook=self.hook)

    def delete(self, rel: str) -> None:
        dest = _check_path(self.project, rel)
        dest.unlink()
        fsync_dir(dest.parent)
        stop = self.project / v.SKILLS_DIR
        d = dest.parent
        while d != stop and d != self.project and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            fsync_dir(d.parent)
            d = d.parent

    def commit(self) -> None:
        self.step("commit:before")
        write_durable(self.txn / COMMITTED, b"committed\n")
        fsync_dir(self.txn)
        self.step("commit:marker")
        _discard(self.project)
        self.step("commit:cleaned")

    def abort(self) -> str | None:
        """Restore after a caught failure. Runs without the fault hook: injected faults model
        the failure being recovered from, not a second failure inside the recovery."""
        return recover(self.project)


def _discard(project: Path) -> None:
    txn = project / TXN_REL
    if txn.is_symlink():
        raise TransactionError("'.tareq/.txn' is a symlink; refusing to remove it")
    shutil.rmtree(txn, ignore_errors=False)
    fsync_dir(txn.parent)


def _load_journal(project: Path) -> dict:
    path = project / TXN_REL / JOURNAL
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
        assert journal["version"] == JOURNAL_VERSION
        for e in journal["entries"]:
            assert isinstance(e["path"], str) and (e["before"] is None or e["before"].startswith("sha256:"))
        assert all(isinstance(d, str) for d in journal["created_dirs"])
    except (OSError, ValueError, KeyError, AssertionError, TypeError, AttributeError) as exc:
        raise TransactionError(f"journal is unreadable or invalid ({exc}); leaving the project "
                               "untouched for manual inspection") from exc
    return journal


def recover(project: Path, hook=None) -> str | None:
    """Repair an interrupted transaction. Returns None (nothing pending), 'discarded',
    'committed', or 'rolled-back'. Must be called with the project lock held."""
    txn = project / TXN_REL
    if txn.is_symlink():
        raise TransactionError("'.tareq/.txn' is a symlink; refusing to recover from it")
    if not txn.exists():
        return None
    if not (txn / JOURNAL).exists():
        _discard(project)  # crashed while snapshotting: nothing was modified yet
        return "discarded"
    if (txn / COMMITTED).exists():
        _discard(project)
        return "committed"
    journal = _load_journal(project)
    entries = journal["entries"]
    for e in entries:  # validate everything before touching anything
        _check_path(project, e["path"])
        if e["backup"]:
            backup = txn / "files" / e["path"]
            if not backup.is_file() or backup.is_symlink() or sha256_bytes(backup.read_bytes()) != e["before"]:
                raise TransactionError(f"backup of '{e['path']}' is missing or corrupt; leaving the "
                                       "project untouched for manual inspection")
    for d in journal["created_dirs"]:
        if not v.clean_segments(d):
            raise TransactionError(f"unsafe directory in journal: {d!r}")
    for i, e in enumerate(entries):
        _hook(hook, f"recover:restore:{i}")
        rel = e["path"]
        dest = _check_path(project, rel)
        current = path_state(project, rel)
        if e["backup"]:
            if current != e["before"]:
                if current is not None and not current.startswith("sha256:"):
                    raise TransactionError(f"'{rel}' is now a {current.split(':')[0]}; cannot restore")
                mkdirs_durable(project, dest.parent)
                write_durable(dest, (txn / "files" / rel).read_bytes(), mode=e.get("mode"))
        elif current is not None:
            if not current.startswith("sha256:"):
                raise TransactionError(f"'{rel}' is now a {current.split(':')[0]}; cannot remove it")
            dest.unlink()
            fsync_dir(dest.parent)
    for e in entries:  # temp files from an interrupted write (before removing directories)
        parent = (project / e["path"]).parent
        if parent.is_dir():
            for tmp in parent.glob(".tareq-tmp-*"):
                tmp.unlink()
    _hook(hook, "recover:dirs")
    for d in reversed(journal["created_dirs"]):
        path = project / d
        if path.is_dir() and not path.is_symlink() and not any(path.iterdir()):
            path.rmdir()
            fsync_dir(path.parent)
    wrong = [e["path"] for e in entries if path_state(project, e["path"]) != e["before"]]
    if wrong:
        raise TransactionError(f"recovery could not restore {wrong}; transaction kept in "
                               f"{TXN_REL} for manual inspection")
    _hook(hook, "recover:discard")
    _discard(project)
    return "rolled-back"
