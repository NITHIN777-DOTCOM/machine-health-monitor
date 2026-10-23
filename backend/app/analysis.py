"""Live per-row analysis: ML health (smoothed), trend forecast, overall status and headline.

Rules of the overall status (DATA_CONTRACT.md section 9):
- overall = the worse of the device rules state and the ML verdict.
- ML is ADVISORY: an ML ANOMALY can raise the overall status to WARNING, never to
  CRITICAL. Only the threshold rules can make it CRITICAL.
- ML status is smoothed so it does not flicker: ANOMALY only after health < 50 for 3
  consecutive rows; it clears only after health > 60 for 5 consecutive rows (settings.json).
- Warm start pre-fills the windows from a recording. For the first window_s live rows the
  feature window spans the joint between recorded and live data, which can look like a
  jump; for those rows ML reports "settling" with no health value and cannot escalate
  ("splice guard"). The forecast works from the first live row.

Uses the same FeatureWindow (features.py) as training, so live scores match offline ones.
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from typing import Any

from .config import Settings
from .device_rules import worst
from .ml.forecast import forecast, forecast_sensors, human_eta
from .ml.scorer import ANOMALY, OK, WARMING_UP, Scorer
from .models import SensorRow
from .registry import Registry

ML_UNAVAILABLE = "ML_UNAVAILABLE"


class Analyzer:
    def __init__(self, registry: Registry, settings: Settings, scorer: Scorer):
        self.registry = registry
        self.settings = settings
        self.scorer = scorer
        self.timing_ms: deque[float] = deque(maxlen=500)
        self.warm_info: dict[str, Any] | None = None
        self.reset()

    # ---- lifecycle ------------------------------------------------------------------
    def reset(self) -> None:
        """New source: empty windows, forget smoothing and any pending warm start."""
        self.hist: deque[SensorRow] = deque()
        self._pending_warm: list[SensorRow] = []
        self.warm_info = None
        self.last: dict[str, Any] | None = None
        self._reset_ml()

    def _reset_ml(self) -> None:
        self.window = self.scorer.make_window()
        self.ml_state = OK
        self._bad = 0
        self._good = 0
        self._splice_rows = 0          # live rows whose window still contains warm-start data

    def set_scorer(self, scorer: Scorer) -> None:
        """Swap the model (reload / retrain). Keeps the forecast history."""
        self.scorer = scorer
        self._reset_ml()

    def warm_start(self, rows: list[SensorRow], file: str) -> int:
        """Queue recorded rows to pre-fill the windows. They are applied, re-timed to end
        just before it, when the next live row arrives, and are never broadcast."""
        self._pending_warm = list(rows)
        self.warm_info = {"file": file, "rows": len(rows), "applied": False,
                          "message": f"warm-start from {file} queued ({len(rows)} rows)"}
        return len(rows)

    def _apply_warm(self, next_row: SensorRow) -> None:
        rows, self._pending_warm = self._pending_warm, []
        if not rows or next_row.ms is None or rows[-1].ms is None:
            return
        offset = next_row.ms - 1000 - rows[-1].ms
        for r in rows:
            shifted = r.with_meta(ms=r.ms + offset)
            if self.window is not None:
                self.window.push_row(shifted)
            self._push_hist(shifted)
        if self.window is not None:
            self._splice_rows = int(round(self.window.window_ms / self.window.period_ms))
        self.warm_info.update(applied=True, message=f"warm-started from {self.warm_info['file']}")

    def _push_hist(self, row: SensorRow) -> None:
        self.hist.append(row)
        while self.hist and self.hist[0].ms <= row.ms - self.settings.forecast_window_s * 1000:
            self.hist.popleft()

    # ---- per row ----------------------------------------------------------------------
    def update(self, row: SensorRow, device: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        if self._pending_warm:
            self._apply_warm(row)
        if row.ms is not None and self.hist and row.ms <= self.hist[-1].ms:
            self.hist.clear()                       # device reset: old trend no longer applies
        feats = self.window.push_row(row) if self.window is not None else None
        if row.ms is not None:
            self._push_hist(row)
        ml = self._ml(feats)
        s = self.settings
        fc = forecast(list(self.hist), self.registry, window_s=s.forecast_window_s,
                      min_r2=s.forecast_min_r2, cap_s=s.forecast_cap_s)
        analysis = self._combine(row, device, ml, fc)
        self.timing_ms.append((time.perf_counter() - t0) * 1000)
        self.last = analysis
        return analysis

    def _ml(self, feats: dict[str, float] | None) -> dict[str, Any]:
        sc = self.scorer
        base = {"status": None, "health": None, "causes": [], "provisional": sc.provisional,
                "warmup_remaining_s": None, "settling_remaining_s": None, "clear_remaining_s": None,
                "instant": None, "message": None}
        if not sc.ready:
            return {**base, "status": sc.status, "message": sc.message}
        if feats is None:
            self.ml_state, self._bad, self._good = OK, 0, 0
            if self.window.full and self.window.missing:
                names = [self._name(k) for k in self.window.missing]
                return {**base, "status": ML_UNAVAILABLE,
                        "message": f"{', '.join(names)}: too many missing values in the last "
                                   f"{self.window.window_ms / 1000:.0f} s"}
            return {**base, "status": WARMING_UP, "warmup_remaining_s": self.window.warmup_remaining_s,
                    "message": "collecting a full window of data"}
        res = sc.score(feats)
        health = res["health"]
        s = self.settings
        if self._splice_rows > 0:
            # The window still spans the joint between recorded and live data, so its score
            # says nothing about the machine: no health shown, no escalation.
            remaining = self._splice_rows
            self._splice_rows -= 1
            return {**base, "status": self.ml_state, "instant": res["ml_status"], "settling_remaining_s": remaining,
                    "message": "settling after warm start (window mixes recorded and live data)"}
        if self.ml_state == ANOMALY:
            self._good = self._good + 1 if health > s.ml_clear_health else 0
            if self._good >= s.ml_clear_rows:
                self.ml_state, self._good = OK, 0
        else:
            self._bad = self._bad + 1 if health < s.ml_anomaly_health else 0
            if self._bad >= s.ml_anomaly_rows:
                self.ml_state, self._bad = ANOMALY, 0
        clearing = self.ml_state == ANOMALY and health > s.ml_clear_health
        return {**base, "status": self.ml_state, "health": health, "causes": res["causes"],
                "instant": res["ml_status"], "range_excess": res.get("range_excess"),
                "clear_remaining_s": s.ml_clear_rows - self._good if clearing else None}

    def _name(self, key: str) -> str:
        s = self.registry.get(key)
        return s.display_name if s else key

    # ---- overall status and headline -------------------------------------------------
    def _combine(self, row: SensorRow, device: dict[str, Any], ml: dict[str, Any],
                 fc: dict[str, dict[str, Any]]) -> dict[str, Any]:
        # The device's own dev_state drives the buzzer, so it is the rules verdict; the
        # backend mirror supplies the reason and hold timer.
        rules = row.dev_state or device["state"]
        ml_flag = ml["status"] == ANOMALY
        overall = worst(rules, "WARNING" if ml_flag else "NORMAL")   # ML never makes it CRITICAL
        rules_flag = rules != "NORMAL"
        source = "both" if rules_flag and ml_flag else "rules" if rules_flag else "ml" if ml_flag else "none"
        forecast_out = {k: {"trend": f["trend"], "status": f["status"], "seconds_to_warn": f["to_warn_s"],
                            "seconds_to_critical": f["to_critical_s"], "to_warn": f["to_warn"],
                            "to_critical": f["to_critical"], "text": f["text"], "r2": f["r2"]}
                        for k, f in fc.items()}
        return {
            "overall": overall,
            "alert_source": source,
            "headline": self._headline(rules, device, ml, fc),
            "device": {"state": device["state"], "reported": row.dev_state, "reason": device["reason"],
                       "hold_remaining_s": device["hold_remaining_s"], "agrees": device.get("agrees")},
            "ml": ml,
            "forecast": forecast_out,
            "warm_start": self.warm_info["message"] if self.warm_info else None,
        }

    def _soonest(self, fc: dict[str, dict[str, Any]]) -> tuple[float, str, str] | None:
        """(seconds, level, sensor key) of the nearest predicted limit crossing, if any."""
        best = None
        for key, f in fc.items():
            for level, secs in (("WARNING", f["to_warn_s"]), ("CRITICAL", f["to_critical_s"])):
                if secs is not None and secs > 0 and (best is None or secs < best[0]):
                    best = (secs, level, key)
        return best

    def _headline(self, rules: str, device: dict[str, Any], ml: dict[str, Any],
                  fc: dict[str, dict[str, Any]]) -> str:
        cap = self.settings.forecast_cap_s
        health = ml["health"]
        crit = [(f["to_critical_s"], k) for k, f in fc.items() if f["to_critical_s"]]
        crit_suffix = ""
        if crit:
            secs, key = min(crit)
            crit_suffix = f"; {self._name(key)} CRITICAL in {human_eta(secs, cap)}"
        if rules != "NORMAL":
            text = f"{device['reason'] or 'Rule limit'} - {rules}"
            if ml["status"] == ANOMALY:
                text += f"; ML anomaly (health {health:.0f})"
            return text + (crit_suffix if rules == "WARNING" else "")
        if ml["status"] == ANOMALY and ml.get("clear_remaining_s"):
            return f"Back to normal - ML anomaly clearing in {ml['clear_remaining_s']} s (health {health:.0f})"
        if ml["status"] == ANOMALY:
            cause = ml["causes"][0]["text"] if ml["causes"] else "Unusual pattern"
            return f"{cause} - ML anomaly (health {health:.0f})" + crit_suffix
        soon = self._soonest(fc)
        if soon:
            secs, level, key = soon
            return f"{self._name(key)} {fc[key]['trend']} - {level} in {human_eta(secs, cap)}"
        if ml["status"] == WARMING_UP:
            return f"Normal - ML warming up ({ml['warmup_remaining_s']:.0f} s)"
        if ml.get("settling_remaining_s"):
            return f"Normal - ML settling after warm start ({ml['settling_remaining_s']} s)"
        if ml["status"] == ML_UNAVAILABLE:
            return f"Normal - ML unavailable ({ml['message']})"
        if ml["status"] not in (OK, ANOMALY):
            return f"Normal - rules only ({ml['message']})"
        return "All normal" + (f" (health {health:.0f})" if health is not None else "")

    # ---- reporting ----------------------------------------------------------------------
    def timing(self) -> dict[str, Any]:
        xs = sorted(self.timing_ms)
        if not xs:
            return {"rows": 0, "avg_ms": None, "p95_ms": None, "max_ms": None}
        return {"rows": len(xs), "avg_ms": round(statistics.mean(xs), 2),
                "p95_ms": round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 2), "max_ms": round(xs[-1], 2)}

    def forecast_keys(self) -> list[str]:
        return [s.key for s in forecast_sensors(self.registry)]


def compact(analysis: dict[str, Any] | None) -> dict[str, Any] | None:
    """Small per-row summary for /api/history (trend charts)."""
    if analysis is None:
        return None
    return {
        "overall": analysis["overall"],
        "alert_source": analysis["alert_source"],
        "ml_status": analysis["ml"]["status"],
        "health": analysis["ml"]["health"],
        "forecast": {k: {"seconds_to_warn": f["seconds_to_warn"], "seconds_to_critical": f["seconds_to_critical"]}
                     for k, f in analysis["forecast"].items()},
    }
