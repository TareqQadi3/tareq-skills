"""Run bin/tareq the way a person at a terminal, or an unattended agent, would.

`run_cli(..., ctty=True)` gives the child a real controlling terminal (a pty) that the test
drives like a human typing; stdout/stderr are separate pipes so the tests can prove the
confirmation prompt never appears there. `ctty=False` runs it with no controlling terminal
at all, like a CI job, cron, or an agent harness's shell tool.
"""
from __future__ import annotations

import fcntl
import os
import pty
import select
import subprocess
import sys
import termios
import time
from dataclasses import dataclass
from pathlib import Path

TAREQ = Path(__file__).resolve().parent.parent / "bin" / "tareq"
PROMPT_END = b"Anything else cancels. > "


@dataclass
class CliResult:
    code: int
    stdout: str
    stderr: str
    tty: str


def clean_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    env.update(extra)
    return env


def run_cli(args, *, answers=None, before_answer=None, ctty=True, env=None, stdin_data=None,
            timeout=120) -> CliResult:
    cmd = [sys.executable, str(TAREQ), *map(str, args)]
    env = clean_env() if env is None else env
    if not ctty:
        r = subprocess.run(cmd, input=stdin_data, capture_output=True, text=True, env=env,
                           start_new_session=True, timeout=timeout,
                           stdin=None if stdin_data is not None else subprocess.DEVNULL)
        return CliResult(r.returncode, r.stdout, r.stderr, "")
    master, slave = pty.openpty()

    def acquire_controlling_tty():
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, start_new_session=True,
                            preexec_fn=acquire_controlling_tty)
    pending = list(answers or [])  # keep `slave` open here so the master never sees EIO early
    seen = b""
    deadline = time.monotonic() + timeout
    try:
        while proc.poll() is None:
            if time.monotonic() > deadline:
                proc.kill()
                raise TimeoutError("tareq did not finish")
            ready, _, _ = select.select([master], [], [], 0.1)
            if not ready:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            seen += chunk
            if seen.endswith(PROMPT_END) and pending:
                if before_answer:
                    before_answer()
                os.write(master, (pending.pop(0) + "\n").encode())
                seen += b"[answered]"
        stdout, stderr = proc.communicate(timeout=timeout)
        try:
            while select.select([master], [], [], 0)[0]:
                seen += os.read(master, 4096)
        except OSError:
            pass
    finally:
        os.close(master)
        os.close(slave)
    return CliResult(proc.returncode, stdout.decode(), stderr.decode(), seen.decode(errors="replace"))
