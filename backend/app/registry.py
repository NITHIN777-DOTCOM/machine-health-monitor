"""Sensor registry: the only place the backend learns which sensors exist.

Loads backend/config/sensors.json (see docs/DATA_CONTRACT.md section 7). Every other
module asks the registry for sensors instead of hard-coding them. Loading never raises:
problems are logged and collected in `Registry.warnings`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import SENSORS_PATH

log = logging.getLogger(__name__)

# Non-sensor columns defined by the contract. Sensor columns come from sensors.json.
TIME_COLUMN = "ms"
STATE_COLUMN = "dev_state"
DIRECTIONS = ("above", "below")
TIERS = ("core", "optional")


@dataclass(frozen=True)
class Sensor:
    key: str
    display_name: str
    unit: str
    hardware: str
    pin: str
    warn: float | None
    critical: float | None
    direction: str
    hysteresis: float | None
    tier: str
    enabled: bool              # effective value (False if its group is in conflict)
    include_in_ml: bool
    group: str | None = None
    comment: str | None = None
    limits_note: str | None = None
    enabled_in_config: bool = True

    @property
    def is_core(self) -> bool:
        return self.tier == "core"

    @property
    def in_ml(self) -> bool:
        return self.enabled and self.include_in_ml

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display_name": self.display_name,
            "unit": self.unit,
            "hardware": self.hardware,
            "pin": self.pin,
            "warn": self.warn,
            "critical": self.critical,
            "direction": self.direction,
            "hysteresis": self.hysteresis,
            "tier": self.tier,
            "enabled": self.enabled,
            "enabled_in_config": self.enabled_in_config,
            "include_in_ml": self.include_in_ml,
            "in_ml": self.in_ml,
            "group": self.group,
            "comment": self.comment,
            "limits_note": self.limits_note,
        }


@dataclass
class Registry:
    schema_version: int | None
    csv_columns: list[str]
    sensors: list[Sensor]
    warnings: list[str] = field(default_factory=list)

    # ---- queries ---------------------------------------------------------------
    @property
    def sensor_keys(self) -> list[str]:
        return [s.key for s in self.sensors]

    @property
    def enabled(self) -> list[Sensor]:
        return [s for s in self.sensors if s.enabled]

    @property
    def ml(self) -> list[Sensor]:
        """Sensors used by ML: enabled AND include_in_ml."""
        return [s for s in self.sensors if s.in_ml]

    def get(self, key: str) -> Sensor | None:
        return next((s for s in self.sensors if s.key == key), None)

    def limits(self, key: str) -> tuple[float | None, float | None, str]:
        """(warn, critical, direction) for a sensor."""
        s = self.get(key)
        if s is None:
            return None, None, "above"
        return s.warn, s.critical, s.direction

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "csv_columns": self.csv_columns,
            "sensors": [s.to_dict() for s in self.sensors],
            "warnings": self.warnings,
        }

    # ---- loading ---------------------------------------------------------------
    @classmethod
    def load(cls, path: Path = SENSORS_PATH) -> "Registry":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("top level must be a JSON object")
        except (OSError, ValueError) as exc:
            msg = f"Could not load sensor registry {path}: {exc}. No sensors are known; every data line will be rejected."
            log.error(msg)
            return cls(schema_version=None, csv_columns=[TIME_COLUMN, STATE_COLUMN], sensors=[], warnings=[msg])
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Registry":
        warnings: list[str] = []

        def warn(msg: str) -> None:
            log.warning("sensors.json: %s", msg)
            warnings.append(msg)

        raw_sensors = data.get("sensors")
        if not isinstance(raw_sensors, list):
            warn("'sensors' is missing or not a list")
            raw_sensors = []

        parsed: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, raw in enumerate(raw_sensors):
            if not isinstance(raw, dict) or not isinstance(raw.get("key"), str) or not raw["key"]:
                warn(f"sensor entry #{i} has no 'key', skipped")
                continue
            key = raw["key"]
            if key in seen or key in (TIME_COLUMN, STATE_COLUMN):
                warn(f"sensor key {key!r} is duplicated or reserved, skipped")
                continue
            seen.add(key)

            direction = raw.get("direction", "above")
            if direction not in DIRECTIONS:
                warn(f"{key}: direction {direction!r} is not 'above'/'below', using 'above'")
                direction = "above"
            tier = raw.get("tier", "optional")
            if tier not in TIERS:
                warn(f"{key}: tier {tier!r} is not 'core'/'optional', using 'optional'")
                tier = "optional"

            parsed.append({
                "key": key,
                "display_name": str(raw.get("display_name") or key),
                "unit": str(raw.get("unit") or ""),
                "hardware": str(raw.get("hardware") or ""),
                "pin": str(raw.get("pin") or ""),
                "warn": _number_or_none(raw.get("warn"), f"{key}.warn", warn),
                "critical": _number_or_none(raw.get("critical"), f"{key}.critical", warn),
                "direction": direction,
                "hysteresis": _hysteresis(raw.get("hysteresis"), key, warn),
                "tier": tier,
                "enabled": bool(raw.get("enabled", False)),
                "include_in_ml": bool(raw.get("include_in_ml", False)),
                "group": raw.get("group") or None,
                "comment": raw.get("comment") or None,
                "limits_note": raw.get("limits_note") or None,
            })

        # Group rule: members must agree on 'enabled', otherwise the whole group is disabled.
        groups: dict[str, list[dict[str, Any]]] = {}
        for p in parsed:
            if p["group"]:
                groups.setdefault(p["group"], []).append(p)
        conflicted = set()
        for name, members in groups.items():
            if len({m["enabled"] for m in members}) > 1:
                detail = ", ".join(f"{m['key']}={m['enabled']}" for m in members)
                warn(f"group {name!r} members disagree on 'enabled' ({detail}); the whole group is treated as DISABLED")
                conflicted.add(name)

        sensors = [
            Sensor(
                **{k: v for k, v in p.items() if k != "enabled"},
                enabled=p["enabled"] and p["group"] not in conflicted,
                enabled_in_config=p["enabled"],
            )
            for p in parsed
        ]

        csv_columns = data.get("csv_columns")
        if not (isinstance(csv_columns, list) and all(isinstance(c, str) for c in csv_columns)):
            warn("'csv_columns' missing or invalid; using ms + sensors (in registry order) + dev_state")
            csv_columns = [TIME_COLUMN, *[s.key for s in sensors], STATE_COLUMN]
        for required in (TIME_COLUMN, STATE_COLUMN):
            if required not in csv_columns:
                warn(f"'csv_columns' has no {required!r} column")
        for s in sensors:
            if s.key not in csv_columns:
                warn(f"sensor {s.key!r} is not in 'csv_columns'; it will never receive values")

        reg = cls(
            schema_version=data.get("schema_version"),
            csv_columns=list(csv_columns),
            sensors=sensors,
            warnings=warnings,
        )
        log.info(
            "Registry loaded: %d sensors, enabled=%s, ml=%s",
            len(sensors), [s.key for s in reg.enabled], [s.key for s in reg.ml],
        )
        return reg


def _hysteresis(value: Any, key: str, warn) -> float | None:
    h = _number_or_none(value, f"{key}.hysteresis", warn)
    if h is not None and h < 0:
        warn(f"{key}.hysteresis = {h} is negative, treated as null (no margin)")
        return None
    return h


def _number_or_none(value: Any, name: str, warn) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    warn(f"{name} = {value!r} is not a number or null, treated as null (TBD)")
    return None
