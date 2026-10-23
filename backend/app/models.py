"""Row model, serial-line parser and CSV helpers (docs/DATA_CONTRACT.md sections 2-5)."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Mapping

from .registry import STATE_COLUMN, TIME_COLUMN, Registry

log = logging.getLogger(__name__)

DEV_STATES = ("NORMAL", "WARNING", "CRITICAL")
MODES = ("live", "recorded", "simulated")
SOURCES = ("real", "synthetic")
LABELS = ("normal", "fault", "unknown")
# Columns the backend adds when storing a row (contract section 5).
META_COLUMNS = ("mode", "source", "label")
TS_COLUMN = "ts_iso"


def now_iso() -> str:
    """Laptop wall-clock time with timezone, second precision."""
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


@dataclass
class SensorRow:
    """One row: the device columns plus the backend's ts_iso/mode/source/label.

    Sensor values are kept in a dict keyed by CSV column name, so the set of sensors
    comes from the registry rather than from this class. Missing values are None.
    """
    ms: int | None
    values: dict[str, float | None]
    dev_state: str | None
    ts_iso: str = field(default_factory=now_iso)
    mode: str = "live"
    source: str = "real"
    label: str = "unknown"

    def with_meta(self, **changes: Any) -> "SensorRow":
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        """Flat JSON-friendly dict in stored column order."""
        return {
            TS_COLUMN: self.ts_iso,
            TIME_COLUMN: self.ms,
            **self.values,
            STATE_COLUMN: self.dev_state,
            "mode": self.mode,
            "source": self.source,
            "label": self.label,
        }

    def to_csv_row(self, registry: Registry) -> list[str]:
        d = self.to_dict()
        return [_fmt(d.get(col)) for col in stored_columns(registry)]


# ---- CSV helpers ---------------------------------------------------------------

def stored_columns(registry: Registry) -> list[str]:
    """ts_iso, the device columns, then mode, source, label."""
    return [TS_COLUMN, *registry.csv_columns, *META_COLUMNS]


def csv_header(registry: Registry) -> list[str]:
    return stored_columns(registry)


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.10g}"
    return str(value)


# ---- parsing -------------------------------------------------------------------

@dataclass
class ParseStats:
    accepted: int = 0
    rejected: int = 0
    comments: int = 0
    last_reject_reason: str | None = None

    def reject(self, reason: str, line: str) -> None:
        self.rejected += 1
        self.last_reject_reason = reason
        log.warning("Rejected line (%d rejected so far): %s: %r", self.rejected, reason, line[:120])


def _parse_number(text: str) -> float | None:
    """'' -> None; otherwise a finite float. Raises ValueError for junk."""
    text = text.strip()
    if text == "":
        return None
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"non-finite value {text!r}")
    return value


def _check_header(line: str, registry: Registry) -> None:
    names = [c.strip() for c in line.lstrip("#").split(",")]
    if names and names[0] == TIME_COLUMN:
        if names != registry.csv_columns:
            log.warning("Device header %s does not match registry csv_columns %s", names, registry.csv_columns)
        else:
            log.info("Device header matches the registry")


def parse_line(
    line: str,
    registry: Registry,
    stats: ParseStats | None = None,
    *,
    mode: str = "live",
    source: str = "real",
    label: str = "unknown",
) -> SensorRow | None:
    """Parse one serial line. Returns None for comments and malformed lines; never raises."""
    stats = stats if stats is not None else ParseStats()
    line = line.strip("\r\n").strip()
    if not line:
        return None
    if line.startswith("#"):
        stats.comments += 1
        _check_header(line, registry)
        return None

    fields = line.split(",")
    columns = registry.csv_columns
    if len(fields) != len(columns):
        stats.reject(f"expected {len(columns)} fields, got {len(fields)}", line)
        return None

    ms: int | None = None
    dev_state: str | None = None
    values: dict[str, float | None] = {}
    try:
        for col, raw in zip(columns, fields):
            if col == TIME_COLUMN:
                num = _parse_number(raw)
                if num is None or not num.is_integer() or num < 0:
                    raise ValueError(f"bad ms {raw!r}")
                ms = int(num)
            elif col == STATE_COLUMN:
                dev_state = raw.strip()
                if dev_state not in DEV_STATES:
                    raise ValueError(f"bad dev_state {raw!r}")
            else:
                values[col] = _parse_number(raw)
    except ValueError as exc:
        stats.reject(str(exc), line)
        return None

    # Sensors in the registry but not in csv_columns still appear, as empty.
    for key in registry.sensor_keys:
        values.setdefault(key, None)

    stats.accepted += 1
    return SensorRow(ms=ms, values=values, dev_state=dev_state, mode=mode, source=source, label=label)


def row_from_stored(record: Mapping[str, str | None], registry: Registry) -> SensorRow:
    """Build a row from a stored CSV record (dict from csv.DictReader). Raises ValueError if malformed."""
    def get(col: str) -> str:
        return (record.get(col) or "").strip()

    ms_val = _parse_number(get(TIME_COLUMN))
    dev_state = get(STATE_COLUMN) or None
    if dev_state is not None and dev_state not in DEV_STATES:
        raise ValueError(f"bad dev_state {dev_state!r}")
    values = {key: _parse_number(get(key)) for key in registry.sensor_keys}
    return SensorRow(
        ms=int(ms_val) if ms_val is not None else None,
        values=values,
        dev_state=dev_state,
        ts_iso=get(TS_COLUMN) or now_iso(),
        mode=get("mode") or "recorded",
        source=get("source") if get("source") in SOURCES else "real",
        label=get("label") if get("label") in LABELS else "unknown",
    )
