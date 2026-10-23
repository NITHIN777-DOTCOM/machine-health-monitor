"""Simulator: generates contract-shaped rows at 1 Hz (times the speed multiplier).

Baselines and scenarios come from backend/config/sim_profile.json. Only sensors that
are enabled in the registry get values; disabled ones are empty, like the real device.
dev_state is computed with app.device_rules.DeviceStateMachine, the same rules
(hysteresis + hold time) the Arduino uses.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from pathlib import Path
from typing import Any, AsyncIterator

from ..config import SIM_PROFILE_PATH
from ..device_rules import DeviceStateMachine
from ..models import SensorRow
from .base import Source

log = logging.getLogger(__name__)


def load_profile(path: Path = SIM_PROFILE_PATH) -> dict[str, Any]:
    """Load sim_profile.json; on error return a minimal profile with only 'normal'."""
    try:
        profile = json.loads(Path(path).read_text(encoding="utf-8"))
        profile.setdefault("sensors", {})
        profile.setdefault("scenarios", {})
        profile["scenarios"].setdefault("normal", {"effects": {}})
        return profile
    except (OSError, ValueError) as exc:
        log.error("Could not load %s (%s); simulator will output empty sensor values", path, exc)
        return {"tick_seconds": 1.0, "sensors": {}, "scenarios": {"normal": {"effects": {}}}}


class SimulatorSource(Source):
    kind = "simulator"

    def __init__(self, *args: Any, scenario: str = "normal", speed: float = 1.0,
                 profile: dict[str, Any] | None = None, seed: int | None = None,
                 hold_seconds: int = 5, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.profile = profile if profile is not None else load_profile()
        if scenario not in self.profile["scenarios"]:
            raise ValueError(f"unknown scenario {scenario!r}; choose from {sorted(self.profile['scenarios'])}")
        self.scenario = scenario
        self.speed = speed
        self.device = DeviceStateMachine(self.registry, hold_seconds)
        self.rng = random.Random(seed)
        self.tick_s = float(self.profile.get("tick_seconds", 1.0))
        self.elapsed_s = 0          # simulated seconds since start
        sc = self.profile["scenarios"][scenario]
        lo, hi = sc.get("start_s", [0, 0])
        self.fault_start_s = self.rng.uniform(lo, hi) if sc.get("effects") else None
        self.ramp_s = float(sc.get("ramp_s", 0)) or None
        self._phase_offsets = {k: self.rng.uniform(0, 2 * math.pi) for k in self.profile["sensors"]}

    # ---- value generation --------------------------------------------------------
    def _baseline(self, key: str, cfg: dict[str, Any], wander_scale: float = 1.0) -> float:
        t = self.elapsed_s
        period = float(cfg.get("wander_period_s", 600)) or 600.0
        v = cfg.get("mean", 0.0)
        v += wander_scale * cfg.get("wander", 0.0) * math.sin(2 * math.pi * t / period + self._phase_offsets.get(key, 0.0))
        v += self.rng.gauss(0, cfg.get("noise", 0.0))
        return min(max(v, cfg.get("min", -math.inf)), cfg.get("max", math.inf))

    @property
    def _progress(self) -> float:
        """0 -> 1 over ramp_s after the fault starts (1 immediately if there is no ramp)."""
        since = self.elapsed_s - (self.fault_start_s or 0)
        return min(1.0, since / self.ramp_s) if self.ramp_s else 1.0

    def _apply_effect(self, value: float, cfg: dict[str, Any], effect: dict[str, Any]) -> float | None:
        """Effects: empty, add, ramp_add, ramp_to, noise. ('steady' is handled in _baseline.)"""
        if effect.get("empty"):
            return None
        progress = self._progress
        if "add" in effect:
            value += effect["add"]
        if "ramp_add" in effect:
            value += effect["ramp_add"] * progress
        if "ramp_to" in effect:
            value += (effect["ramp_to"] - cfg.get("mean", value)) * progress
        if "noise" in effect:
            value += self.rng.gauss(0, effect["noise"])
        return value

    @property
    def fault_active(self) -> bool:
        return self.fault_start_s is not None and self.elapsed_s >= self.fault_start_s

    def make_row(self) -> SensorRow:
        effects = self.profile["scenarios"][self.scenario].get("effects", {}) if self.fault_active else {}
        values: dict[str, float | None] = {}
        for sensor in self.registry.sensors:
            cfg = self.profile["sensors"].get(sensor.key)
            if not sensor.enabled or cfg is None:
                values[sensor.key] = None
                continue
            effect = effects.get(sensor.key, {})
            # "steady": fade out the slow wander as the ramp progresses, so the ramp ends
            # at mean + ramp_add instead of wherever the wander happens to be.
            wander_scale = 1.0 - self._progress if effect.get("steady") else 1.0
            v: float | None = self._baseline(sensor.key, cfg, wander_scale)
            if sensor.key in effects:
                v = self._apply_effect(v, cfg, effects[sensor.key])
            if v is not None:
                v = min(max(v, cfg.get("physical_min", -math.inf)), cfg.get("physical_max", math.inf))
                v = float(round(v, int(cfg.get("decimals", 1))))
            values[sensor.key] = v

        sc = self.profile["scenarios"][self.scenario]
        label = sc.get("label_after_start", "fault") if self.fault_active else "normal"
        return SensorRow(
            ms=int(self.elapsed_s * 1000),
            values=values,
            dev_state=self.device.update(values),
            mode="simulated",
            source="synthetic",
            label=label,
        )

    async def rows(self) -> AsyncIterator[SensorRow]:
        await self._set_status(connected=True, error=None)
        log.info("Simulator started: scenario=%s speed=%sx fault_at=%s",
                 self.scenario, self.speed,
                 f"{self.fault_start_s:.0f}s" if self.fault_start_s is not None else "never")
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while True:
            yield self.make_row()
            self.elapsed_s += self.tick_s
            next_tick += self.tick_s / self.speed
            await asyncio.sleep(max(0.0, next_tick - loop.time()))

    def status(self) -> dict[str, Any]:
        return {
            **super().status(),
            "scenario": self.scenario,
            "speed": self.speed,
            "elapsed_s": self.elapsed_s,
            "fault_active": self.fault_active,
        }
