"""Row pipeline: source -> device mirror -> process(row) (ML + forecast) -> broadcast + history + recorder.

One source runs at a time as a background task. switch() stops the old source and
starts a new one without restarting the server.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .analysis import Analyzer
from .device_rules import DeviceStateMachine
from .ml import dataset
from .ml.jobs import TrainJobs
from .ml.scorer import Scorer
from .config import Settings
from .models import SensorRow
from .recorder import Recorder
from .registry import Registry
from .sources import ReplaySource, SerialSource, SimulatorSource, Source
from .sources.replay import resolve_recording
from .version import version_info
from .sources.serial_source import port_exists, resolve_port
from .sources.simulator import load_profile
from .state import AppState, RingBuffer

log = logging.getLogger(__name__)

SERIAL_CHECK_S = 5.0
STATUS_TICK_S = 1.0     # status push interval while recording or replaying
REJECT_RECENT_S = 15.0  # a rejected line this recent means "data is arriving, wrong format"


class Pipeline:
    def __init__(self, state: AppState, scorer: Scorer | None = None):
        self.state = state
        self.source: Source | None = None
        self._task: asyncio.Task[None] | None = None
        self.sim_profile = load_profile()
        # Backend mirror of the device-tier rules. For simulated rows it matches dev_state
        # exactly; for live rows it explains the device's state (reason, hold timer).
        self.device = DeviceStateMachine(state.registry, state.settings.hold_seconds)
        self.device_reported: str | None = None
        self._last_ms: int | None = None    # device clock of the last row (reset detection)
        # Link debounce: a source counts as connected while it is starting up (grace period)
        # or while rows keep arriving; only grace seconds without data mean "disconnected".
        self._started_at = time.monotonic()
        self._last_row_at: float | None = None
        self._rejected_mark = state.parse_stats.rejected   # rejected count at the last good row
        self._reported_connected: bool | None = None
        self._watchdog: asyncio.Task[None] | None = None
        # ML + forecast. The model is loaded once; reload_model() swaps it at runtime.
        self.scorer = scorer if scorer is not None else Scorer.load(state.registry, state.settings.models_dir)
        self.analyzer = Analyzer(state.registry, state.settings, self.scorer)
        self.train_jobs = TrainJobs(state.registry, state.settings, on_done=self.reload_model)
        self._serial_cache: tuple[float, dict[str, Any]] | None = None
        self._last_notify = 0.0

    @classmethod
    def offline(cls, registry: Registry, settings: Settings, scorer: Scorer | None) -> "Pipeline":
        """A pipeline for offline evaluation (ml/evaluation.py): only process(row) is used, so
        a recording gets exactly the live analysis (mirror, smoothed ML, forecast). Nothing is
        recorded or broadcast. scorer None = no model."""
        state = AppState(registry=registry, settings=settings,
                         recorder=Recorder(registry, settings.recordings_dir), history=RingBuffer(1, 1))
        return cls(state, scorer if scorer is not None else Scorer(registry))

    def reset_analysis(self) -> None:
        """Forget the device mirror, ML windows/smoothing and forecast history (new source)."""
        self.state.history.clear()
        self.device.reset()
        self.device_reported = None
        self._last_ms = None
        self.analyzer.reset()

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
            if st.settings.force_source == "simulator":
                raise ValueError("serial is disabled by MHM_SOURCE=simulator (unset it and restart to use the Arduino)")
            return SerialSource(**common, settings=st.settings, label_getter=self.live_label)
        if type == "replay":
            if not file:
                raise ValueError("replay needs 'file' (a name from GET /api/recordings)")
            path = resolve_recording(st.settings.recording_dirs, file)
            return ReplaySource(**common, path=path, speed=speed, loop=loop)
        raise ValueError(f"unknown source type {type!r}; use simulator, serial or replay")

    def live_label(self) -> str:
        return self.state.recorder.label or "unknown"

    # ---- running -----------------------------------------------------------------------
    async def switch(self, source: Source, warmstart_file: str | None = None) -> None:
        """Start a new source. A warm start given here is queued before the source produces
        its first row, so the stream never shows "warming up"."""
        await self.stop()
        self.source = source
        self.reset_analysis()
        if warmstart_file:
            self.warm_start(warmstart_file)
        self._started_at = time.monotonic()
        self._last_row_at = None
        self._rejected_mark = self.state.parse_stats.rejected
        self._task = asyncio.create_task(self._run(source), name=f"source-{source.kind}")
        if self._watchdog is None or self._watchdog.done():
            self._watchdog = asyncio.create_task(self._watch_link(), name="link-watchdog")
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

    async def shutdown(self) -> None:
        await self.train_jobs.shutdown()
        await self.stop()
        watchdog, self._watchdog = self._watchdog, None
        if watchdog is not None:
            watchdog.cancel()
            try:
                await watchdog
            except asyncio.CancelledError:
                pass

    async def _watch_link(self) -> None:
        """Push a status message when the debounced connected flag flips without any event,
        and once a second while recording or replaying (row count, elapsed time, progress)."""
        while True:
            await asyncio.sleep(0.25)
            ticking = self.state.recorder.active or isinstance(self.source, ReplaySource)
            if (self.link()["connected"] != self._reported_connected
                    or (ticking and time.monotonic() - self._last_notify >= STATUS_TICK_S)):
                await self.notify_status()

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

    def process(self, row: SensorRow) -> dict:
        """Device-state mirror, then features + ML score + forecast -> the row's analysis block."""
        if row.ms is not None and self._last_ms is not None and row.ms < self._last_ms:
            # The device restarted (USB replug, reset button, watchdog): its state machine
            # starts again at NORMAL, so the mirror must too (HIL 2026-10-24: the mirror kept
            # CRITICAL for 11 rows after a replug).
            self.device.reset()
        self._last_ms = row.ms if row.ms is not None else self._last_ms
        self.device.update(row.values)
        self.device_reported = row.dev_state
        return self.analyzer.update(row, self.device_status())

    async def handle(self, row: SensorRow) -> None:
        st = self.state
        analysis = self.process(row)
        self._last_row_at = time.monotonic()
        self._rejected_mark = st.parse_stats.rejected
        st.rows_received += 1
        st.history.append(row, analysis)
        st.recorder.write(row)            # raw contract row only: recordings stay clean training data
        await st.broadcaster.send({"type": "row", "mode": row.mode, "row": row.to_dict(), "analysis": analysis})

    # ---- warm start and model ------------------------------------------------------------
    def warm_start(self, file: str) -> int:
        """Pre-fill the ML window and forecast history from the last W+60 s of a recording.
        Raises FileNotFoundError / ValueError."""
        path = resolve_recording(self.state.settings.recording_dirs, file)
        data = dataset.load([str(path)], self.state.registry)
        rows = data.segments[-1].rows if data.segments else []
        rows = [r for r in rows if r.ms is not None]
        if not rows:
            raise ValueError(f"{file} has no usable rows")
        window_s = self.scorer.meta.get("window_s", self.state.settings.ml_window_s)
        keep_ms = (window_s + self.state.settings.forecast_window_s) * 1000
        rows = [r for r in rows if r.ms > rows[-1].ms - keep_ms]
        n = self.analyzer.warm_start(rows, path.name)
        log.info("Warm start queued from %s: %d rows", path.name, n)
        return n

    async def reload_model(self) -> dict:
        self.scorer = Scorer.load(self.state.registry, self.state.settings.models_dir)
        self.analyzer.set_scorer(self.scorer)
        log.info("Model reloaded: %s", self.scorer.status)
        await self.notify_status()
        return self.model_info()

    def model_info(self) -> dict:
        m = self.scorer.meta
        training = m.get("training", {})
        return {
            **self.scorer.info(),
            "trained_on": training.get("rows_normal_by_source"),
            "training_windows": training.get("windows"),
            "training_files": training.get("files"),
            "feature_count": len(m.get("feature_names", [])),
            "calibration": m.get("calibration"),
            "range_excess": m.get("range_excess"),
            "sklearn_version": m.get("sklearn_version"),
            "provisional_reason": m.get("provisional_reason"),
            "ml_thresholds": self.ml_thresholds(),
        }

    # ---- status ------------------------------------------------------------------------
    def link(self) -> dict[str, Any]:
        """Debounced connection state.

        link: "starting" (new source, within the grace period), "ok" (rows arriving),
        "no_data" (source open but silent for grace seconds), "down" (port/source error
        for grace seconds), "finished" (replay ended).

        silent_s: seconds without a good row (since the source started if none came yet).
        rejecting: lines ARE arriving but are all rejected (wrong sketch or baud rate):
        lines were rejected since the last good row, the newest within REJECT_RECENT_S
        (an I2C scanner sketch, for example, only prints every few seconds).
        """
        grace = self.state.settings.link_grace_s
        now = time.monotonic()
        src = self.source
        age = None if self._last_row_at is None else now - self._last_row_at
        if src is None:
            state = "down"
        elif src.finished:
            state = "finished"
        elif age is not None and age < grace:
            state = "ok"
        elif now - self._started_at < grace:
            state = "starting"
        else:
            state = "no_data" if src.connected else "down"
        stats = self.state.parse_stats
        rejected_recent = stats.rejected - self._rejected_mark
        rejecting = (rejected_recent > 0 and stats.last_reject_at is not None
                     and now - stats.last_reject_at < REJECT_RECENT_S)
        return {
            "connected": state in ("ok", "starting"),
            "link": state,
            "data_age_s": None if age is None else round(age, 1),
            "silent_s": round(age if age is not None else now - self._started_at, 1),
            "rejecting": rejecting,
            "rejected_recent": rejected_recent,
        }

    def status(self) -> dict[str, Any]:
        st = self.state
        src = self.source.status() if self.source else {}
        return {
            "source": src.get("type"),
            "scenario": src.get("scenario"),
            "speed": src.get("speed"),
            "file": src.get("file"),
            "loop": src.get("loop"),
            "progress": src.get("progress"),       # replay only: share of the file played, 0..1
            "serial_port": src.get("serial_port"),
            **self.link(),
            "last_error": src.get("last_error"),
            "source_detail": src,
            "device": self.device_status(),
            "analysis": self.analyzer.last,
            "model": self.scorer.info(),
            "warm_start": self.analyzer.warm_info,
            "analysis_timing_ms": self.analyzer.timing(),
            "recording": st.recorder.status(),
            "rows_received": st.rows_received,
            "rows_rejected": st.parse_stats.rejected,
            "last_reject_reason": st.parse_stats.last_reject_reason,
            "last_rejected_line": st.parse_stats.last_rejected_line,
            "history_rows": len(st.history),
            "startup_reason": st.startup_reason,
            "registry_warnings": st.registry.warnings,
            "scenarios": sorted(self.sim_profile["scenarios"]),
            "ml_thresholds": self.ml_thresholds(),
            "serial": self.serial_info(),
            "version": version_info(),
        }

    def serial_info(self) -> dict[str, Any]:
        """Whether switching to serial can work, for the dashboard's source switcher.
        MHM_SOURCE=simulator never lists ports; otherwise the port list is checked at most
        every SERIAL_CHECK_S seconds (status is sent often)."""
        if self.state.settings.force_source == "simulator":
            return {"available": False, "port": None,
                    "note": ("Serial disabled: simulator-only mode (MHM_SOURCE=simulator, "
                             "--simulator or 'Start (simulator only).bat'). Restart with Start.bat to use the Arduino.")}
        if isinstance(self.source, SerialSource):
            return {"available": True, "port": self.source.status().get("serial_port"), "note": None}
        now = time.monotonic()
        if self._serial_cache is None or now - self._serial_cache[0] > SERIAL_CHECK_S:
            try:
                port, how = resolve_port(self.state.settings)
                ok = port is not None and (how == "auto-detected" or port_exists(port))
                info = {"available": ok, "port": port if ok else None,
                        "note": None if ok else "No Arduino found. Plug in the Uno and close the Arduino IDE Serial Monitor."}
            except Exception as exc:  # noqa: BLE001 - a port listing error must not break status
                info = {"available": False, "port": None, "note": f"Could not list serial ports: {exc}"}
            self._serial_cache = (now, info)
        return self._serial_cache[1]

    def ml_thresholds(self) -> dict[str, float]:
        """ML smoothing levels (settings.json), so the dashboard draws them without hard-coding."""
        s = self.state.settings
        return {"anomaly_health": s.ml_anomaly_health, "anomaly_rows": s.ml_anomaly_rows,
                "clear_health": s.ml_clear_health, "clear_rows": s.ml_clear_rows}

    def device_status(self) -> dict[str, Any]:
        """Mirror state machine snapshot, plus what the device itself reported."""
        snap = self.device.snapshot()
        snap["device_reported"] = self.device_reported
        snap["agrees"] = None if self.device_reported is None else self.device_reported == snap["state"]
        return snap

    async def notify_status(self) -> None:
        status = self.status()
        self._reported_connected = status["connected"]
        self._last_notify = time.monotonic()
        await self.state.broadcaster.send({"type": "status", "status": status})
