"""Time-to-limit forecast: a linear trend per sensor. Pure function, no model needed, so it
keeps working when ML is off.

For every enabled sensor that has a warn and/or critical limit:
  - fit value = a + b*t over the last `window_s` seconds of the device clock (ms)
  - if there are too few points          -> "insufficient_data"
  - if the fitted value is already at/past a limit -> that limit is "reached"
  - if the trend points towards the limit (b > 0 for direction "above", b < 0 for
    "below") and the fit is good (R^2 >= min_r2) -> seconds until the fitted line
    crosses the limit; more than cap_s is reported as "> 30 min"
  - otherwise                            -> "stable"
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from ..registry import Registry, Sensor

MIN_COVERAGE = 0.5   # need values for at least half of the window's seconds


def _fmt_eta(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f} s"
    return f"{seconds / 60:.0f} min"


def _fit(t: np.ndarray, v: np.ndarray) -> tuple[float, float, float]:
    """slope, intercept, R^2 of a least-squares line."""
    tc = t - t.mean()
    denom = float((tc * tc).sum())
    if denom == 0:
        return 0.0, float(v.mean()), 0.0
    slope = float((tc * (v - v.mean())).sum() / denom)
    intercept = float(v.mean() - slope * t.mean())
    ss_tot = float(((v - v.mean()) ** 2).sum())
    ss_res = float(((v - (intercept + slope * t)) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return slope, intercept, r2


def _past(value: float, limit: float, direction: str) -> bool:
    return value >= limit if direction == "above" else value <= limit


def forecast_sensor(sensor: Sensor, rows: Sequence[Any], *, window_s: float = 60, min_r2: float = 0.6,
                    cap_s: float = 1800) -> dict[str, Any]:
    out: dict[str, Any] = {"sensor": sensor.key, "status": "insufficient_data", "trend": None,
                           "slope_per_s": None, "r2": None, "to_warn_s": None, "to_critical_s": None,
                           "to_warn": None, "to_critical": None, "text": None}
    timed = [r for r in rows if r.ms is not None]
    if not timed:
        return out
    now_ms = timed[-1].ms
    pts = [((r.ms - now_ms) / 1000.0, r.values.get(sensor.key)) for r in timed
           if r.ms > now_ms - window_s * 1000 and r.values.get(sensor.key) is not None]
    if len(pts) < max(5, MIN_COVERAGE * window_s):
        return out
    t = np.array([p[0] for p in pts])
    v = np.array([p[1] for p in pts], dtype=float)
    slope, intercept, r2 = _fit(t, v)
    level = intercept                      # fitted value now (t = 0)
    towards = slope > 0 if sensor.direction == "above" else slope < 0
    trusted = towards and r2 >= min_r2
    out.update(slope_per_s=round(slope, 5), r2=round(r2, 3),
               trend=("rising" if slope > 0 else "falling") if trusted else "stable")

    any_eta = False
    for name, limit in (("warn", sensor.warn), ("critical", sensor.critical)):
        if limit is None:
            continue
        if _past(level, limit, sensor.direction):
            out[f"to_{name}_s"], out[f"to_{name}"] = 0.0, "reached"
            any_eta = True
        elif trusted:
            eta = (limit - level) / slope
            if eta > cap_s:
                out[f"to_{name}"] = f"> {cap_s / 60:.0f} min"
            else:
                out[f"to_{name}_s"], out[f"to_{name}"] = round(eta, 1), _fmt_eta(eta)
                any_eta = True

    if out["to_critical"] == "reached" or out["to_warn"] == "reached":
        out["status"] = "reached"
    elif any_eta:
        out["status"] = "approaching"
    else:
        out["status"] = "stable"
    def describe(lvl: str) -> str:
        when = out[f"to_{lvl}"]
        if when == "reached" or when.startswith(">"):
            return f"{lvl.upper()} {when}"
        return f"{lvl.upper()} in ~{when}"

    parts = [describe(lvl) for lvl in ("warn", "critical") if out[f"to_{lvl}"] is not None]
    out["text"] = f"{sensor.display_name}: " + (", ".join(parts) if parts else "stable")
    return out


def forecast(rows: Sequence[Any], registry: Registry, *, window_s: float = 60, min_r2: float = 0.6,
             cap_s: float = 1800) -> dict[str, dict[str, Any]]:
    """Forecast every enabled sensor that has at least one limit. rows: oldest first,
    objects with .ms and .values (SensorRow)."""
    return {s.key: forecast_sensor(s, rows, window_s=window_s, min_r2=min_r2, cap_s=cap_s)
            for s in registry.enabled if s.warn is not None or s.critical is not None}


def predicts_critical(fc: dict[str, dict[str, Any]]) -> bool:
    """True if any sensor is forecast to reach (or has reached) its critical limit within the cap."""
    return any(f["to_critical_s"] is not None for f in fc.values())
