"""Replay a stored recording from data/recordings at original speed or a multiplier.

Rows keep their original source and label; mode becomes "recorded" and ts_iso is
re-stamped with the current time so the dashboard plots them as they arrive.
"""
from __future__ import annotations

import asyncio
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

from ..models import TS_COLUMN, SensorRow, now_iso, row_from_stored
from ..registry import TIME_COLUMN
from .base import Source

log = logging.getLogger(__name__)

MAX_GAP_S = 10.0  # gaps longer than this in a recording are shortened


def resolve_recording(recordings_dir: Path, name: str) -> Path:
    """Map a file name to a path inside recordings_dir. Raises FileNotFoundError."""
    base = recordings_dir.resolve()
    path = (base / name).resolve()
    if path.parent != base or path.suffix.lower() != ".csv" or not path.is_file():
        raise FileNotFoundError(f"No recording named {name!r} in {recordings_dir}")
    return path


def _seconds(record: dict[str, str], prev: dict[str, str] | None) -> float:
    """Time between two stored records.

    Uses the device clock (ms) first: for simulated recordings made at 5x/10x the
    wall-clock ts_iso gaps are compressed, but ms is simulated time. Falls back to
    ts_iso if ms is missing or jumps (device reset), else 1 s.
    """
    if prev is None:
        return 0.0
    try:
        gap = (float(record[TIME_COLUMN]) - float(prev[TIME_COLUMN])) / 1000.0
        if 0 < gap <= MAX_GAP_S:
            return gap
    except (KeyError, TypeError, ValueError):
        pass
    try:
        return (datetime.fromisoformat(record[TS_COLUMN]) - datetime.fromisoformat(prev[TS_COLUMN])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return 1.0


class ReplaySource(Source):
    kind = "replay"

    def __init__(self, *args: Any, path: Path, speed: float = 1.0, loop: bool = False, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.path = path
        self.speed = speed
        self.loop = loop
        self.rows_played = 0
        self.passes = 0
        self._sleep = asyncio.sleep  # replaceable in tests

    async def rows(self) -> AsyncIterator[SensorRow]:
        await self._set_status(connected=True, error=None)
        log.info("Replaying %s at %sx%s", self.path.name, self.speed, " (looping)" if self.loop else "")
        while True:
            prev: dict[str, str] | None = None
            with self.path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(line for line in f if not line.startswith("#"))
                for record in reader:
                    gap = min(max(_seconds(record, prev), 0.0), MAX_GAP_S)
                    prev = record
                    try:
                        row = row_from_stored(record, self.registry)
                    except ValueError as exc:
                        self.stats.reject(f"{self.path.name}: {exc}", ",".join(str(v) for v in record.values()))
                        continue
                    if gap:
                        await self._sleep(gap / self.speed)
                    self.rows_played += 1
                    yield row.with_meta(mode="recorded", ts_iso=now_iso())
            self.passes += 1
            if not self.loop:
                break
        self.finished = True
        await self._set_status(connected=False, error=None)
        log.info("Replay of %s finished (%d rows)", self.path.name, self.rows_played)

    def status(self) -> dict[str, Any]:
        return {
            **super().status(),
            "file": self.path.name,
            "speed": self.speed,
            "loop": self.loop,
            "rows_played": self.rows_played,
        }
