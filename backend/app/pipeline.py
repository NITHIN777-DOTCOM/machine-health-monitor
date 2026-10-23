"""Row pipeline: source -> process(row) -> broadcast + history + recorder.

One source runs at a time as a background task. switch() stops the old source and
starts a new one without restarting the server.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .device_rules import DeviceStateMachine
from .models import SensorRow
from .sources import ReplaySource, SerialSource, SimulatorSource, Source
from .sources.replay import resolve_recording
from .sources.simulator import load_profile
from .state import AppState

log = logging.getLogger(__name__)


def process(row: SensorRow, state: AppState) -> SensorRow:
    """Per-row processing step. Currently a pass-through."""
    # Phase 3: rules + ML here (backend-side rule evaluation, anomaly score, prediction).
    return row


class Pipeline:
    def __init__(self, state: AppState):
        self.state = state
        self.source: Source | None = None
        self._task: asyncio.Task[None] | None = None
        self.sim_profile = load_profile()
        # Backend mirror of the device-tier rules. For simulated rows it matches dev_state
        # exactly; for live rows it explains the device's state (reason, hold timer).
        self.device = DeviceStateMachine(state.registry, state.settings.hold_seconds)
        self.device_reported: str | None = None

    # ---- source construction ---------------------------------------------------------
    def make_source(self, type: str, scenario: str | None = None, speed: float | None = None,
                    file: str | None = None, loop: bool = False) -> Source:
        """Build a source from API parameters. Raises ValueError / FileNotFoundError."""
        st = self.state
        common = dict(registry=st.registry, stats=st.parse_stats, on_change=self.notify_status)
        speed = 1.0 if speed is None else float(speed)
        if not 0 < speed <= st.settings.max_speed:
            raise ValueError(f"speed must be > 0 and <= {st.settings.max_speed}")
        if type == "simulator":
            return SimulatorSource(**common, scenario=scenario or "normal", speed=speed, profile=self.sim_profile,
                                   hold_seconds=st.settings.hold_seconds)
        if type == "serial":
            return SerialSource(**common, settings=st.settings, label_getter=self.live_label)
        if type == "replay":
            if not file:
                raise ValueError("replay needs 'file' (a name from GET /api/recordings)")
            path = resolve_recording(st.settings.recordings_dir, file)
            return ReplaySource(**common, path=path, speed=speed, loop=loop)
        raise ValueError(f"unknown source type {type!r}; use simulator, serial or replay")

    def live_label(self) -> str:
        return self.state.recorder.label or "unknown"

    # ---- running -----------------------------------------------------------------------
    async def switch(self, source: Source) -> None:
        await self.stop()
        self.source = source
        self.state.history.clear()
        self.device.reset()
        self.device_reported = None
        self._task = asyncio.create_task(self._run(source), name=f"source-{source.kind}")
        log.info("Source switched to %s", source.kind)
        await self.notify_status()

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self.source is not None:
            await self.source.close()

    async def _run(self, source: Source) -> None:
        try:
            async for row in source.rows():
                await self.handle(row)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a broken source must not kill the server
            log.exception("Source %s crashed", source.kind)
            source.last_error = f"Source crashed: {exc}"
            source.connected = False
        await self.notify_status()

    async def handle(self, row: SensorRow) -> None:
        st = self.state
        row = process(row, st)
        self.device.update(row.values)
        self.device_reported = row.dev_state
        st.rows_received += 1
        st.history.append(row)
        st.recorder.write(row)
        await st.broadcaster.send({"type": "row", "mode": row.mode, "row": row.to_dict(), "device": self.device_status()})

    # ---- status ------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        st = self.state
        src = self.source.status() if self.source else {}
        return {
            "source": src.get("type"),
            "scenario": src.get("scenario"),
            "speed": src.get("speed"),
            "file": src.get("file"),
            "loop": src.get("loop"),
            "serial_port": src.get("serial_port"),
            "connected": src.get("connected", False),
            "last_error": src.get("last_error"),
            "source_detail": src,
            "device": self.device_status(),
            "recording": st.recorder.status(),
            "rows_received": st.rows_received,
            "rows_rejected": st.parse_stats.rejected,
            "history_rows": len(st.history),
            "startup_reason": st.startup_reason,
            "registry_warnings": st.registry.warnings,
            "scenarios": sorted(self.sim_profile["scenarios"]),
        }

    def device_status(self) -> dict[str, Any]:
        """Mirror state machine snapshot, plus what the device itself reported."""
        snap = self.device.snapshot()
        snap["device_reported"] = self.device_reported
        snap["agrees"] = None if self.device_reported is None else self.device_reported == snap["state"]
        return snap

    async def notify_status(self) -> None:
        await self.state.broadcaster.send({"type": "status", "status": self.status()})
