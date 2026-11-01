"""Logging must never touch stdout: it is the MCP JSON-RPC channel."""

from __future__ import annotations

import io
import logging

from relay.util.log import get_logger


def test_logger_writes_to_a_stream_handler_not_stdout() -> None:
    logger = get_logger("test")
    relay_root = logging.getLogger("relay")

    captured = io.StringIO()
    streams = [
        handler
        for handler in relay_root.handlers
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
    ]
    assert streams, "relay must log to a stream handler (stderr) by default"

    originals = [handler.setStream(captured) for handler in streams]
    try:
        logger.info("hello from the test")
    finally:
        for handler, original in zip(streams, originals, strict=True):
            handler.setStream(original)

    assert "hello from the test" in captured.getvalue()


def test_no_stream_handler_targets_the_real_stdout() -> None:
    import sys

    handlers = logging.getLogger("relay").handlers

    assert not any(
        isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout
        for handler in handlers
    )
