"""Logging that can never corrupt the MCP stdio channel.

Rule: every handler writes to stderr or a file. Nothing in this module touches stdout.

Why this matters: an MCP server speaks JSON-RPC over stdout. One stray write makes the host see
malformed input and drop the connection, usually with no error shown to the user.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

RELAY_HOME = Path(os.environ.get("RELAY_HOME", Path.home() / ".relay"))

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s :: %(message)s"
_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return

    root = logging.getLogger("relay")
    root.setLevel(logging.DEBUG)
    root.propagate = False

    formatter = logging.Formatter(_FORMAT)

    stderr = logging.StreamHandler(sys.stderr)
    stderr.setLevel(logging.DEBUG if os.environ.get("RELAY_DEBUG") else logging.INFO)
    stderr.setFormatter(formatter)
    root.addHandler(stderr)

    # File logging is best-effort: a read-only home is not a reason to fail.
    try:
        log_dir = RELAY_HOME / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "relay.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    except OSError:
        pass

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger. Safe to call from anywhere, including the MCP server."""
    _configure()
    return logging.getLogger(f"relay.{name}")
