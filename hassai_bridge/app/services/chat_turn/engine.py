"""Boundary for running one chat turn without depending on the HTTP connection.

The durable chat_jobs runner and the live SSE path both ultimately drive the
same turn through a registered coroutine factory. Events (thinking, tools,
assistant preview) are pushed via TurnEvents rather than writing SSE directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

log = logging.getLogger("hassai.chat_turn")

TurnRunner = Callable[..., Awaitable[dict[str, Any]]]


class TurnEvents(Protocol):
    async def emit(self, event: dict) -> None: ...

    def is_cancelled(self) -> bool: ...


@dataclass
class MemoryTurnEvents:
    """In-memory event sink used by tests and the durable runner."""

    events: list[dict] = field(default_factory=list)
    cancelled: bool = False
    on_emit: Callable[[dict], Awaitable[None] | None] | None = None

    async def emit(self, event: dict) -> None:
        payload = dict(event or {})
        self.events.append(payload)
        if self.on_emit:
            result = self.on_emit(payload)
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]

    def is_cancelled(self) -> bool:
        return self.cancelled


_registered_runner: TurnRunner | None = None


def register_turn_runner(runner: TurnRunner | None) -> None:
    """Register the coroutine that executes a prepared chat turn."""
    global _registered_runner
    _registered_runner = runner


def get_turn_runner() -> TurnRunner | None:
    return _registered_runner


async def run_registered_turn(**kwargs: Any) -> dict[str, Any]:
    """Invoke the registered turn runner (wired from routers.chat at import)."""
    runner = _registered_runner
    if runner is None:
        raise RuntimeError("chat turn runner is not registered")
    return await runner(**kwargs)
