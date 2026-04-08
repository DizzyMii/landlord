"""Async event pub/sub system for tenant-to-landlord communication."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class Event:
    """An event emitted by a tenant or the system."""

    tenant_id: str
    event_type: str
    payload: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Simple async pub/sub. Callbacks are awaited directly on publish."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], Awaitable[None]]]] = defaultdict(list)

    async def subscribe(self, event_type: str, callback: Callable[[Event], Awaitable[None]]) -> None:
        self._subscribers[event_type].append(callback)

    async def unsubscribe(self, event_type: str, callback: Callable[[Event], Awaitable[None]]) -> None:
        callbacks = self._subscribers.get(event_type, [])
        if callback in callbacks:
            callbacks.remove(callback)

    async def publish(self, event: Event) -> None:
        for callback in self._subscribers.get(event.event_type, []):
            await callback(event)
