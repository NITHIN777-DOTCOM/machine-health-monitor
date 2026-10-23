"""Rolling-window features. The ONE implementation used by training, evaluation and live scoring.

The window is defined on the device clock (`ms`), not wall time, so 10x replay or
simulation gives exactly the same features as 1x.

For every ML sensor (registry: enabled AND include_in_ml) and a window of W seconds:
    mean, std, min, max, slope (least squares, units per second), last
Feature names are "<sensor>__<stat>", e.g. "vib_count__mean".

No value is ever invented: until the window is full, or if a sensor is missing in more
than max_missing_frac of the window's expected samples, the result is None ("warming up").
"""
from __future__ import annotations

from collections import deque
from typing import Mapping, Sequence

import numpy as np

from ..registry import Registry

STATS = ("mean", "std", "min", "max", "slope", "last")


def ml_sensor_keys(registry: Registry) -> list[str]:
    """Sensors used by ML, in registry order. Never hard-coded."""
    return [s.key for s in registry.ml]


def feature_names(sensor_keys: Sequence[str]) -> list[str]:
    return [f"{key}__{stat}" for key in sensor_keys for stat in STATS]


def split_feature(name: str) -> tuple[str, str]:
    key, _, stat = name.rpartition("__")
    return key, stat


class FeatureWindow:
    """Feed rows in order with push(); each call returns the features of the window that
    ends at that row, or None while warming up.

    A row whose ms is not after the previous one (device reset, new recording) restarts
    the window.
    """

    def __init__(self, sensors: Sequence[str], window_s: float = 10, max_missing_frac: float = 0.3,
                 period_s: float = 1.0):
        if window_s < 2:
            raise ValueError("window_s must be at least 2 seconds")
        self.sensors = list(sensors)
        self.names = feature_names(self.sensors)
        self.window_ms = window_s * 1000.0
        self.period_ms = period_s * 1000.0
        self.expected = int(round(window_s / period_s))   # samples in a full window
        self.max_missing_frac = max_missing_frac
        self._buf: deque[tuple[int, Mapping[str, float | None]]] = deque()
        self._first_ms: int | None = None
        self._last_ms: int | None = None
        self.missing: list[str] = []      # sensors missing too much in the last full window

    def reset(self) -> None:
        self._buf.clear()
        self._first_ms = None
        self._last_ms = None
        self.missing = []

    def push_row(self, row) -> dict[str, float] | None:
        """Convenience for SensorRow-like objects (with .ms and .values)."""
        return self.push(row.ms, row.values)

    def push(self, ms: int | None, values: Mapping[str, float | None]) -> dict[str, float] | None:
        if ms is None:
            return None
        if self._buf and ms <= self._buf[-1][0]:
            self.reset()
        if self._first_ms is None:
            self._first_ms = ms
        self._last_ms = ms
        self._buf.append((ms, values))
        while self._buf and self._buf[0][0] <= ms - self.window_ms:
            self._buf.popleft()
        if ms - self._first_ms < self.window_ms - self.period_ms:
            return None                                    # window not full yet
        return self._compute(ms)

    @property
    def full(self) -> bool:
        return (self._first_ms is not None and self._buf
                and self._buf[-1][0] - self._first_ms >= self.window_ms - self.period_ms)

    @property
    def warmup_remaining_s(self) -> float:
        """Seconds of data still needed before the first full window."""
        covered = 0 if self._first_ms is None else self._last_ms - self._first_ms + self.period_ms
        return max(0.0, (self.window_ms - covered) / 1000.0)

    def _compute(self, now_ms: int) -> dict[str, float] | None:
        out: dict[str, float] = {}
        self.missing = []
        for key in self.sensors:
            pts = [(ms, vals.get(key)) for ms, vals in self._buf if vals.get(key) is not None]
            missing = 1.0 - len(pts) / self.expected
            if missing > self.max_missing_frac + 1e-9 or len(pts) < 2:
                self.missing.append(key)
                continue
            t = np.array([(ms - now_ms) / 1000.0 for ms, _ in pts])
            v = np.array([float(x) for _, x in pts])
            tc = t - t.mean()
            denom = float((tc * tc).sum())
            slope = float((tc * (v - v.mean())).sum() / denom) if denom > 0 else 0.0
            out[f"{key}__mean"] = float(v.mean())
            out[f"{key}__std"] = float(v.std())
            out[f"{key}__min"] = float(v.min())
            out[f"{key}__max"] = float(v.max())
            out[f"{key}__slope"] = slope
            out[f"{key}__last"] = float(v[-1])
        return None if self.missing else out


def to_vector(features: Mapping[str, float], names: Sequence[str]) -> np.ndarray:
    return np.array([[features[n] for n in names]], dtype=float)
