"""Per-project exclusive lock (F1): at most one sync/rollback/recover/note/init at a time.

`fcntl.flock` on `.tareq/.lock`: held by the open file description, released by the kernel
when the process exits or is killed, so a crash can never leave a stale lock. Advisory and
POSIX-only; not reliable on network filesystems that do not implement flock (documented).
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import stat
import threading
from pathlib import Path

from .fsutil import UnsafePathError

LOCK_REL = ".tareq/.lock"
_held = threading.local()


class ProjectBusy(RuntimeError):
    pass


def held(project: Path) -> bool:
    return project.resolve() in getattr(_held, "paths", set())


def assert_held(project: Path) -> None:
    if not held(project):
        raise RuntimeError("internal error: project mutation attempted without holding the "
                           "project lock")


@contextlib.contextmanager
def project_lock(project: Path):
    project = project.resolve()
    directory = project / ".tareq"
    if directory.is_symlink():
        raise UnsafePathError("'.tareq' is a symlink; refusing to use it")
    directory.mkdir(exist_ok=True)
    try:
        fd = os.open(directory / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
                     | getattr(os, "O_CLOEXEC", 0), 0o644)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise UnsafePathError("'.tareq/.lock' is a symlink; refusing to use it") from exc
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise UnsafePathError("'.tareq/.lock' is not a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EACCES):
                raise ProjectBusy("another tareq sync/rollback/note is running on this project; "
                                  "wait for it to finish and retry") from exc
            raise
        paths = getattr(_held, "paths", None)
        if paths is None:
            paths = _held.paths = set()
        paths.add(project)
        try:
            yield
        finally:
            paths.discard(project)
    finally:
        os.close(fd)
