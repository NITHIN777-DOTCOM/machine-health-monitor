"""Device-tier rules: the dev_state logic the Arduino runs (DATA_CONTRACT.md section 3).

Shared by the simulator, the pipeline (backend mirror of the device) and the tests. The
firmware copies the same logic in Phase 7.

Levels: NORMAL < WARNING < CRITICAL.

Escalation is immediate. In the same row that any of these happens, the state rises:
  - a value reaches its warn limit (in the sensor's direction)       -> WARNING
  - a value reaches its critical limit                                -> CRITICAL
  - an enabled core sensor sends an empty field (sensor fault)        -> WARNING

De-escalation is slow, one level at a time. It needs BOTH:
  - every value is clear of the current level's limit by the sensor's hysteresis
    margin (e.g. temp_c below 35 - 0.5 = 34.5 to leave CRITICAL), no core fault for
    leaving WARNING, AND
  - that has been true for hold_seconds consecutive rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .registry import Registry, Sensor

LEVELS = ("NORMAL", "WARNING", "CRITICAL")
_RANK = {name: i for i, name in enumerate(LEVELS)}


def worst(*states: str) -> str:
    return max(states, key=_RANK.__getitem__, default="NORMAL")


def _breaches(value: float, limit: float | None, direction: str, margin: float = 0.0) -> bool:
    """True if value is at/past limit. A margin moves the limit towards 'safe' (hysteresis)."""
    if limit is None:
        return False
    return value >= limit - margin if direction == "above" else value <= limit + margin


@dataclass(frozen=True)
class Trigger:
    """One reason for a state: a sensor past a limit, or a core sensor fault."""
    sensor: str
    display_name: str
    hardware: str
    kind: str            # "limit" or "fault"
    level: str           # WARNING or CRITICAL
    value: float | None = None
    limit: float | None = None
    direction: str = "above"
    in_band: bool = False  # past limit-minus-hysteresis but not the limit itself

    @property
    def text(self) -> str:
        if self.kind == "fault":
            return f"SENSOR FAULT: {self.hardware or self.sensor}"
        name = "crit" if self.level == "CRITICAL" else "warn"
        if self.in_band:
            return f"{self.display_name} {self.value:g} near {name} {self.limit:g} (hysteresis)"
        op = ">=" if self.direction == "above" else "<="
        return f"{self.display_name} {self.value:g} {op} {name} {self.limit:g}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor": self.sensor, "kind": self.kind, "level": self.level, "value": self.value,
            "limit": self.limit, "direction": self.direction, "in_band": self.in_band, "text": self.text,
        }


def sensor_state(sensor: Sensor, value: float | None, margin: float = 0.0) -> str:
    """State caused by one sensor's value (ignores the fault rule)."""
    if value is None:
        return "NORMAL"
    if _breaches(value, sensor.critical, sensor.direction, margin):
        return "CRITICAL"
    if _breaches(value, sensor.warn, sensor.direction, margin):
        return "WARNING"
    return "NORMAL"


def triggers(values: Mapping[str, float | None], registry: Registry, use_hysteresis: bool = False) -> list[Trigger]:
    """Everything currently pushing the state above NORMAL.

    use_hysteresis=False: the plain limits (used for escalation).
    use_hysteresis=True:  limits moved by each sensor's hysteresis margin (used to decide
                          whether a level has really cleared).
    """
    out: list[Trigger] = []
    for s in registry.enabled:
        value = values.get(s.key)
        if value is None:
            if s.is_core:
                out.append(Trigger(s.key, s.display_name, s.hardware, "fault", "WARNING"))
            continue
        margin = (s.hysteresis or 0.0) if use_hysteresis else 0.0
        level = sensor_state(s, value, margin)
        if level != "NORMAL":
            limit = s.critical if level == "CRITICAL" else s.warn
            in_band = not _breaches(value, limit, s.direction)
            out.append(Trigger(s.key, s.display_name, s.hardware, "limit", level, value, limit, s.direction, in_band))
    return out


def level_of(trigs: list[Trigger]) -> str:
    return worst(*(t.level for t in trigs)) if trigs else "NORMAL"


def evaluate(values: Mapping[str, float | None], registry: Registry) -> tuple[str, list[str]]:
    """Stateless, instantaneous level and reasons (no hysteresis, no hold)."""
    trigs = triggers(values, registry)
    return level_of(trigs), list(dict.fromkeys(t.text for t in trigs))


class DeviceStateMachine:
    """Stateful dev_state with immediate escalation and hysteresis + hold de-escalation.

    Call update() once per row (one row = one second on the device). Create a new one
    or call reset() when the data source changes.
    """

    def __init__(self, registry: Registry, hold_seconds: int = 5):
        self.registry = registry
        self.hold_seconds = max(0, int(hold_seconds))
        self.reset()

    def reset(self) -> None:
        self.state = "NORMAL"
        self.hold_count = 0          # consecutive rows the current level has been clear
        self.clearing = False
        self.reasons: list[Trigger] = []
        self.last_change: str | None = None   # e.g. "WARNING -> CRITICAL"

    def update(self, values: Mapping[str, float | None]) -> str:
        instant = level_of(triggers(values, self.registry))
        sticky_trigs = triggers(values, self.registry, use_hysteresis=True)
        sticky = level_of(sticky_trigs)
        before = self.state

        if _RANK[instant] > _RANK[self.state]:
            # Escalate immediately, possibly by two levels.
            self.state = instant
            self.hold_count = 0
        elif _RANK[sticky] < _RANK[self.state]:
            # Clear of the current level (with margin): count towards the hold.
            self.hold_count += 1
            if self.hold_count >= self.hold_seconds:
                self.state = LEVELS[_RANK[self.state] - 1]   # one level down only
                self.hold_count = 0
        else:
            self.hold_count = 0

        self.clearing = _RANK[sticky] < _RANK[self.state]
        active = [t for t in sticky_trigs if _RANK[t.level] >= _RANK[self.state]]
        if self.state == "NORMAL":
            self.reasons = []
        elif active:
            self.reasons = active
        # else: clearing; keep the reasons that put us here so the LCD can still show them
        if self.state != before:
            self.last_change = f"{before} -> {self.state}"
        return self.state

    @property
    def hold_remaining_s(self) -> int | None:
        return self.hold_seconds - self.hold_count if self.clearing else None

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": "; ".join(dict.fromkeys(t.text for t in self.reasons)) or None,
            "reasons": [t.to_dict() for t in self.reasons],
            "clearing": self.clearing,
            "hold_remaining_s": self.hold_remaining_s,
            "hold_seconds": self.hold_seconds,
            "last_change": self.last_change,
        }
