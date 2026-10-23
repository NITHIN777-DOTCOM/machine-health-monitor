"""Device-tier rules: the same dev_state logic the Arduino runs (DATA_CONTRACT.md section 3).

- value at/over the warn limit (in the sensor's direction)     -> WARNING
- value at/over the critical limit                              -> CRITICAL
- an enabled core sensor with an empty field (sensor fault)     -> at least WARNING
The result is the worst of all of these.
"""
from __future__ import annotations

from typing import Mapping

from .registry import Registry, Sensor

_SEVERITY = {"NORMAL": 0, "WARNING": 1, "CRITICAL": 2}


def worst(*states: str) -> str:
    return max(states, key=_SEVERITY.__getitem__, default="NORMAL")


def _breaches(value: float, limit: float | None, direction: str) -> bool:
    if limit is None:
        return False
    return value >= limit if direction == "above" else value <= limit


def sensor_state(sensor: Sensor, value: float | None) -> str:
    """State caused by one sensor's value (ignores the fault rule)."""
    if value is None:
        return "NORMAL"
    if _breaches(value, sensor.critical, sensor.direction):
        return "CRITICAL"
    if _breaches(value, sensor.warn, sensor.direction):
        return "WARNING"
    return "NORMAL"


def evaluate(values: Mapping[str, float | None], registry: Registry) -> tuple[str, list[str]]:
    """Return (dev_state, reasons). Reasons are short LCD-style strings."""
    state = "NORMAL"
    reasons: list[str] = []
    for sensor in registry.enabled:
        value = values.get(sensor.key)
        if value is None:
            if sensor.is_core:
                state = worst(state, "WARNING")
                reasons.append(f"SENSOR FAULT: {sensor.hardware or sensor.key}")
            continue
        s = sensor_state(sensor, value)
        if s != "NORMAL":
            state = worst(state, s)
            reasons.append(f"{s}: {sensor.display_name}")
    # One physical module (e.g. DHT11) can produce several fault reasons; keep one each.
    return state, list(dict.fromkeys(reasons))


def dev_state(values: Mapping[str, float | None], registry: Registry) -> str:
    return evaluate(values, registry)[0]
