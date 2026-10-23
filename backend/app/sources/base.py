"""Common interface for row sources (simulator, serial, replay).

A source is an async iterator of SensorRow. It reports its own status (connected,
last error, ...) through `status()` and calls `on_change` whenever that status changes,
so the pipeline can push a status message to the dashboard.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Awaitable, Callable

from ..models import ParseStats, SensorRow
from ..registry import Registry

log = logging.getLogger(__name__)

StatusCallback = Callable[[], Awaitable[None]]


class Source(ABC):
    kind: str = "base"

    def __init__(self, registry: Registry, stats: ParseStats, on_change: StatusCallback | None = None):
        self.registry = registry
        self.stats = stats
        self.on_change = on_change
        self.connected = False
        self.last_error: str | None = None
        self.finished = False

    async def _set_status(self, *, connected: bool | None = None, error: str | None | object = ...) -> None:
        """Update connected/last_error and notify listeners if anything changed."""
        changed = False
        if connected is not None and connected != self.connected:
            self.connected = connected
            changed = True
        if error is not ... and error != self.last_error:
            self.last_error = error  # type: ignore[assignment]
            changed = True
        if changed and self.on_change:
            await self.on_change()

    @abstractmethod
    def rows(self) -> AsyncIterator[SensorRow]:
        """Yield rows until the source ends or the task is cancelled."""

    async def close(self) -> None:
        """Release resources (serial port, files). Safe to call more than once."""

    def status(self) -> dict[str, Any]:
        return {
            "type": self.kind,
            "connected": self.connected,
            "last_error": self.last_error,
            "finished": self.finished,
        }
