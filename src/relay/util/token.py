"""Bearer token shared by the daemon and every local client.

One file, owner-only permissions, created on first use. The token never appears in a URL or a log
line; it travels in an ``Authorization`` header over loopback.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path

from .log import RELAY_HOME

TOKEN_PATH = RELAY_HOME / "token"


def read_or_create_token(path: Path | None = None) -> str:
    """Return the bearer token, creating it with mode 0600 if it does not exist yet."""
    target = path or TOKEN_PATH

    if target.exists():
        existing = target.read_text(encoding="utf-8").strip()
        if existing:
            _restrict(target)
            return existing

    target.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)

    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # An empty file from a previous interrupted run: replace it, do not loop.
        fd = os.open(target, os.O_WRONLY | os.O_TRUNC, 0o600)

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")

    _restrict(target)
    return token


def _restrict(path: Path) -> None:
    """Best-effort 0600. A failure here is not a reason to refuse to start."""
    with contextlib.suppress(OSError):
        path.chmod(0o600)


__all__ = ["TOKEN_PATH", "read_or_create_token"]
