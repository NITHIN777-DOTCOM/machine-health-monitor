"""Test helpers shared by several test modules."""
from __future__ import annotations

import asyncio
from typing import Any

from app.models import ParseStats, SensorRow
from app.registry import Registry
from app.sources.simulator import SimulatorSource

RANK = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}


def sensor(key, warn, critical, direction="above", hysteresis=None, tier="core", enabled=True, **kw):
    """A sensors.json entry for a fake registry."""
    return {"key": key, "display_name": key.upper(), "hardware": key.upper() + "-HW", "warn": warn,
            "critical": critical, "direction": direction, "hysteresis": hysteresis, "tier": tier,
            "enabled": enabled, "include_in_ml": True, "forecast": True, **kw}


def make_reg(*sensors) -> Registry:
    return Registry.from_dict({
        "csv_columns": ["ms", *[s["key"] for s in sensors], "dev_state"],
        "sensors": list(sensors),
    })


def rows_from(values: list[dict], *, step_ms: int = 1000, start_ms: int = 0, **meta) -> list[SensorRow]:
    """SensorRows at a fixed device-clock step from a list of value dicts."""
    return [SensorRow(ms=start_ms + i * step_ms, values=v, dev_state=meta.get("dev_state", "NORMAL"),
                      mode=meta.get("mode", "live"), source=meta.get("source", "real"),
                      label=meta.get("label", "normal")) for i, v in enumerate(values)]


def sim_rows(registry: Registry, scenario: str, seconds: int, seed: int, source: str = "synthetic",
             profile: dict | None = None) -> list[SensorRow]:
    """Simulator rows stepped directly, with the given source."""
    from app.sources.simulator import load_profile
    sim = SimulatorSource(registry=registry, stats=ParseStats(), scenario=scenario,
                          profile=profile or load_profile(), seed=seed)
    rows = []
    for _ in range(seconds):
        r = sim.make_row()
        r.source = source
        rows.append(r)
        sim.elapsed_s += 1
    return rows


def run_scenario(registry: Registry, profile: dict, scenario: str, seconds: int, seed: int = 0,
                 hold_seconds: int = 5) -> tuple[list[SensorRow], list[dict[str, Any]]]:
    """Step the simulator `seconds` times directly (no asyncio, no sleeping)."""
    sim = SimulatorSource(registry=registry, stats=ParseStats(), scenario=scenario,
                          profile=profile, seed=seed, hold_seconds=hold_seconds)
    rows, snaps = [], []
    for _ in range(seconds):
        rows.append(sim.make_row())
        snaps.append(sim.device.snapshot())
        sim.elapsed_s += sim.tick_s
    return rows, snaps


def transitions(states: list[str]) -> list[tuple[int, str, str]]:
    """[(index, old, new)] for every change of state."""
    return [(i, states[i - 1], states[i]) for i in range(1, len(states)) if states[i] != states[i - 1]]


def collapse(seq: list) -> list:
    """Remove consecutive duplicates: [A, A, B, A] -> [A, B, A]."""
    return [x for i, x in enumerate(seq) if i == 0 or x != seq[i - 1]]


def reversals_within(states: list[str], window: int) -> list[tuple[int, int]]:
    """Pairs of consecutive transitions in opposite directions less than `window` rows apart."""
    tr = transitions(states)
    out = []
    for (i0, a0, b0), (i1, a1, b1) in zip(tr, tr[1:]):
        if (RANK[b0] > RANK[a0]) != (RANK[b1] > RANK[a1]) and i1 - i0 < window:
            out.append((i0, i1))
    return out


async def collect(source, n: int, timeout: float = 3.0) -> list[SensorRow]:
    """Take n rows from a source's async iterator, then close it."""
    out: list[SensorRow] = []
    agen = source.rows()

    async def take():
        async for row in agen:
            out.append(row)
            if len(out) >= n:
                return

    try:
        await asyncio.wait_for(take(), timeout)
    finally:
        await agen.aclose()
    return out
