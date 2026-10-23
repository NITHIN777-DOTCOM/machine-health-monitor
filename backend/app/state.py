"""Shared in-memory state: registry, settings, history ring buffer, WebSocket clients."""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from .config import Settings
from .models import ParseStats, SensorRow
from .recorder import Recorder
from .registry import Registry

log = logging.getLogger(__name__)


class RingBuffer:
    """Rows (with their live analysis) from the last `seconds` of wall-clock time."""

    def __init__(self, seconds: float, max_speed: float):
        self.seconds = seconds
        # Cap the length so 10x/20x replay or simulation can't grow memory without bound.
        self._rows: deque[tuple[float, SensorRow, dict[str, Any] | None]] = deque(
            maxlen=int(seconds * max(1.0, max_speed)) + 1)

    def append(self, row: SensorRow, analysis: dict[str, Any] | None = None) -> None:
        now = time.monotonic()
        self._rows.append((now, row, analysis))
        while self._rows and self._rows[0][0] < now - self.seconds:
            self._rows.popleft()

    def since(self, seconds: float) -> list[tuple[SensorRow, dict[str, Any] | None]]:
        cutoff = time.monotonic() - seconds
        return [(row, analysis) for t, row, analysis in self._rows if t >= cutoff]

    def clear(self) -> None:
        self._rows.clear()

    def __len__(self) -> int:
        return len(self._rows)


class Broadcaster:
    """Sends JSON messages to every connected WebSocket client; drops dead ones."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def send(self, message: dict[str, Any]) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - a closed socket must not stop the stream
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


@dataclass
class AppState:
    registry: Registry
    settings: Settings
    recorder: Recorder
    history: RingBuffer
    broadcaster: Broadcaster = field(default_factory=Broadcaster)
    parse_stats: ParseStats = field(default_factory=ParseStats)
    rows_received: int = 0
    startup_reason: str = ""
