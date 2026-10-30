"""Explicit, tool-enforced approval (D-26).

A plan fingerprint is an identifier, never proof of approval. The only approval channel this
tool accepts is a human typing a confirmation on the controlling terminal (`/dev/tty`), which
a non-interactive caller (pipe, `yes`, a harness without a terminal, CI, cron) cannot satisfy.
If no such channel exists, apply FAILS CLOSED. There is no flag, environment variable, or
config option that skips this check.

Honest limit: code that deliberately allocates its own pseudo-terminal and types the
confirmation can still satisfy it. Defending against that needs an approval channel outside
the agent's execution environment (not implemented; see docs/architecture/approval.md).
"""
from __future__ import annotations

import datetime as _dt
import getpass
import os
import select
import time
from dataclasses import dataclass

# Heuristic only (an agent can unset it): refuse inside a known agent harness even if a
# terminal happens to be reachable. Only markers observed in a real session are listed.
AGENT_ENV_MARKERS = ("CLAUDECODE",)
ACCEPTED_CHANNELS = frozenset({"tty"})
DEFAULT_TIMEOUT = 300.0


class ApprovalError(RuntimeError):
    """Base class: no valid approval for this plan."""


class ApprovalUnavailable(ApprovalError):
    """This environment cannot establish explicit approval; apply is refused (fail closed)."""


class ApprovalDenied(ApprovalError):
    """A terminal was available but the human did not confirm."""


@dataclass(frozen=True)
class Approval:
    fingerprint: str
    channel: str
    approver: str
    at: str


def sanitize_for_terminal(text: str) -> str:
    """Drop control characters (ESC sequences, CR, BEL, ...) so nothing in a summary can
    redraw, hide, or forge the confirmation prompt. Newlines and tabs are kept."""
    return "".join(ch for ch in text if ch in "\n\t" or (ord(ch) >= 0x20 and ord(ch) != 0x7F
                                                       and not 0x80 <= ord(ch) <= 0x9F))


def confirmation_phrase(fingerprint: str) -> str:
    digest = fingerprint.split(":", 1)[1]
    return f"apply {digest[:12]}"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def check_shape(approval) -> Approval:
    """The object must be an Approval from an accepted channel (a fingerprint is not one)."""
    if not isinstance(approval, Approval):
        raise ApprovalError("apply requires an Approval obtained through an approval channel; "
                            "a fingerprint string is not approval")
    if approval.channel not in ACCEPTED_CHANNELS:
        raise ApprovalError(f"approval channel {approval.channel!r} is not accepted")
    return approval


def require(approval, fingerprint: str) -> Approval:
    """Library-level gate used by apply_plan: the approval must come from an accepted channel
    and be bound to exactly this plan fingerprint (R-15, R-20)."""
    check_shape(approval)
    if approval.fingerprint != fingerprint:
        raise ApprovalError("approval does not match the current plan fingerprint; the source, "
                            "destination, settings, or operations changed. Create a new plan "
                            "and approve it (R-20).")
    return approval


def request_tty_approval(*, summary: str, fingerprint: str, action: str,
                         timeout: float = DEFAULT_TIMEOUT, tty_path: str = "/dev/tty",
                         environ=None) -> Approval:
    environ = os.environ if environ is None else environ
    for marker in AGENT_ENV_MARKERS:
        if environ.get(marker):
            raise ApprovalUnavailable(
                f"refusing to ask for approval inside an agent harness ({marker} is set). "
                "Run the printed command yourself in a terminal outside the agent session.")
    try:
        fd = os.open(tty_path, os.O_RDWR | os.O_NOCTTY)
    except OSError as exc:
        raise ApprovalUnavailable(
            f"no controlling terminal ({exc.strerror}); explicit approval cannot be "
            "established in this environment, so nothing was applied. Run the command in an "
            "interactive terminal.") from exc
    try:
        if not os.isatty(fd):
            raise ApprovalUnavailable(f"{tty_path} is not a terminal; nothing was applied")
        phrase = confirmation_phrase(fingerprint)
        try:
            prompt = (f"\n===== tareq: approval required to {action} =====\n{summary}\n\n"
                      f"To approve exactly this plan, type: {phrase}\n"
                      "Anything else cancels. > ")
            os.write(fd, sanitize_for_terminal(prompt).encode("utf-8"))
            deadline = time.monotonic() + timeout
            line = b""
            while b"\n" not in line:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ApprovalDenied("approval timed out; nothing was applied")
                ready, _, _ = select.select([fd], [], [], remaining)
                if not ready:
                    continue
                chunk = os.read(fd, 256)
                if not chunk:
                    raise ApprovalDenied("terminal closed; nothing was applied")
                line += chunk
                if len(line) > 4096:
                    raise ApprovalDenied("input too long; nothing was applied")
        except OSError as exc:  # hangup / I/O error on the terminal
            raise ApprovalDenied(f"terminal error ({exc.strerror}); nothing was applied") from exc
        typed = line.decode("utf-8", errors="replace").strip()
        if typed != phrase:
            raise ApprovalDenied("confirmation did not match; nothing was applied")
        try:
            who = getpass.getuser()
        except Exception:  # noqa: BLE001 - uid without passwd entry
            who = f"uid-{os.getuid()}"
        return Approval(fingerprint=fingerprint, channel="tty", approver=who, at=_now())
    finally:
        os.close(fd)
