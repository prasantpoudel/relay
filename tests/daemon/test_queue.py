"""Per-provider serialisation.

The invariant: one prompt in flight per provider, any number across providers. Tests use events,
not sleeps, so they cannot pass by accident on a fast machine.
"""

from __future__ import annotations

import asyncio

from relay.daemon.queue import ProviderQueues


async def _wait_for(predicate: object, timeout: float = 1.0) -> None:
    """Yield to the loop until a zero-arg predicate is true."""

    def check() -> bool:
        return bool(predicate())  # type: ignore[operator]

    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.001)


async def test_same_provider_is_serialised() -> None:
    queues = ProviderQueues()
    order: list[str] = []

    async def job(name: str) -> None:
        async with queues.slot("chatgpt"):
            order.append(f"{name}-in")
            await asyncio.sleep(0.02)
            order.append(f"{name}-out")

    await asyncio.gather(job("a"), job("b"))

    assert order == ["a-in", "a-out", "b-in", "b-out"]


async def test_different_providers_run_in_parallel() -> None:
    queues = ProviderQueues()
    started: list[str] = []
    release = asyncio.Event()

    async def job(provider: str) -> None:
        async with queues.slot(provider):
            started.append(provider)
            await release.wait()

    first = asyncio.create_task(job("chatgpt"))
    second = asyncio.create_task(job("gemini"))

    await _wait_for(lambda: len(started) == 2)
    release.set()
    await asyncio.gather(first, second)

    assert set(started) == {"chatgpt", "gemini"}


async def test_depth_counts_running_and_waiting() -> None:
    queues = ProviderQueues()
    release = asyncio.Event()
    observed: list[int] = []

    async def job() -> None:
        async with queues.slot("chatgpt"):
            observed.append(queues.depth("chatgpt"))
            await release.wait()

    first = asyncio.create_task(job())
    await _wait_for(lambda: queues.depth("chatgpt") == 1)

    second = asyncio.create_task(job())
    await _wait_for(lambda: queues.depth("chatgpt") == 2)

    release.set()
    await asyncio.gather(first, second)

    assert observed == [1, 1]
    assert queues.depth("chatgpt") == 0


async def test_slot_is_released_when_the_body_raises() -> None:
    queues = ProviderQueues()

    try:
        async with queues.slot("chatgpt"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert queues.depth("chatgpt") == 0

    async with queues.slot("chatgpt"):
        assert queues.depth("chatgpt") == 1


async def test_depths_are_reported_per_provider() -> None:
    queues = ProviderQueues()

    async with queues.slot("chatgpt"):
        assert queues.depth("chatgpt") == 1
        assert queues.depth("gemini") == 0

    assert queues.depth("chatgpt") == 0
