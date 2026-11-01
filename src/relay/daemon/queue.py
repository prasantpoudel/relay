"""Per-provider serialisation.

One lock per provider plus a depth counter for diagnostics. Different providers run in parallel —
that is a feature, not an accident: fanning out to ChatGPT and Gemini at once should be fast.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class ProviderQueues:
    """Hands out one exclusive slot per provider id."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._depth: dict[str, int] = {}

    def _lock_for(self, provider_id: str) -> asyncio.Lock:
        lock = self._locks.get(provider_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[provider_id] = lock
        return lock

    @asynccontextmanager
    async def slot(self, provider_id: str) -> AsyncIterator[None]:
        """Hold the provider's only slot for the duration of the block, including on error."""
        lock = self._lock_for(provider_id)
        self._depth[provider_id] = self._depth.get(provider_id, 0) + 1
        try:
            async with lock:
                yield
        finally:
            self._depth[provider_id] -= 1

    def depth(self, provider_id: str) -> int:
        """Number of callers inside or waiting on a provider's slot."""
        return self._depth.get(provider_id, 0)


__all__ = ["ProviderQueues"]
