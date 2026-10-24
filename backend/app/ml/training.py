"""Train the IsolationForest anomaly model on NORMAL rows only.

Health calibration (stored in model_meta.json, used by scorer.health_from_score):
  s = IsolationForest score_samples() of a window (higher = more normal)
  m = median score of the training (normal) windows          -> 100
  t = the model's decision threshold (offset_, ~1% quantile) -> 50
  r = (s - t) / (m - t)
  IF part = 50 + 50 * r (max 100) when r >= 0, else 50 / (1 - r) (soft decay: 25 at one
  "normal spread" below the threshold, 12.5 at three). IF scores saturate outside the
  training data, so the IF part alone never says 0.

Range excess: IsolationForest cannot tell HOW FAR outside the training range a value is
(a vibration of 80 lands in the same leaf as the largest normal value, 7). So the scorer
also measures, per feature, how many training standard deviations the value lies beyond
the training min/max and takes the largest ("excess"). Range part =
100 - K * ln(1 + excess / B), clamped 0..100 (K = 16.7, B = 0.28): moderately out-of-range
values give a mid score (vibration 13 vs a normal 0-6: ~35), extreme ones reach 0.
health = min(IF part, range part). Training windows have excess 0 by definition, so the
calibration above is unchanged.
"""
from __future__ import annotations

import json
import platform
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest

from ..registry import Registry
from .dataset import Dataset
from .features import FeatureWindow, feature_names, ml_sensor_keys, ml_stats
from .scorer import RANGE_B, RANGE_K, health_from_score

MIN_WINDOWS = 50
STD_FLOOR = 1e-3


CALIBRATION_RULE = ("r = (score - threshold)/(median - threshold); IF part = 50 + 50*r (max 100) if r >= 0, "
                    "else 50/(1 - r); health = min(IF part, range part)")
RANGE_EXCESS_META = {
    "k": RANGE_K,
    "b": RANGE_B,
    "rule": "excess = max over features of (distance beyond training min/max) / training std; "
            "range part = 100 - k*ln(1 + excess/b), clamped 0..100",
}


class TrainingError(Exception):
    pass


def build_training_matrix(dataset: Dataset, sensors: list[str], window_s: float,
                          max_missing_frac: float, names: list[str] | None = None) -> tuple[np.ndarray, dict[str, Any]]:
    """Window features from label=normal rows only. Any other row breaks the window, so
    no training window ever contains a fault or unknown row."""
    names = names or feature_names(sensors)
    X: list[list[float]] = []
    rows_used: Counter = Counter()
    windows: Counter = Counter()
    skipped: Counter = Counter()
    for seg in dataset.segments:
        fw = FeatureWindow(sensors, window_s, max_missing_frac)
        for row in seg.rows:
            if row.label != "normal":
                skipped[row.label] += 1
                fw.reset()
                continue
            rows_used[row.source] += 1
            feats = fw.push_row(row)
            if feats is not None:
                X.append([feats[n] for n in names])
                windows[row.source] += 1
    info = {
        "rows_normal_by_source": {"real": rows_used.get("real", 0), "synthetic": rows_used.get("synthetic", 0)},
        "windows_by_source": {"real": windows.get("real", 0), "synthetic": windows.get("synthetic", 0)},
        "rows_skipped_not_normal": dict(skipped),
    }
    return np.array(X, dtype=float).reshape(-1, len(names)), info


def calibrate(scores: np.ndarray, threshold: float) -> dict[str, float]:
    median = float(np.median(scores))
    if median <= threshold:                      # degenerate: keep the map well-defined
        median = threshold + 1e-6
    return {
        "median_score": median,
        "threshold_score": float(threshold),
        "abnormal_score": float(threshold - (median - threshold)),
        "rule": CALIBRATION_RULE,
    }


def train(dataset: Dataset, registry: Registry, *, window_s: float = 10, max_missing_frac: float = 0.3,
          n_estimators: int = 200, contamination: float = 0.01, random_state: int = 42,
          sessions: list[str] | None = None, extra_meta: dict[str, Any] | None = None,
          stats: dict[str, list[str]] | None = None,
          ) -> tuple[IsolationForest, dict[str, Any]]:
    """Fit on the label=normal rows of `dataset`. sessions: the recording sessions behind the
    real rows (MANIFEST.json names, for the meta); extra_meta overrides/extends the meta
    (status line, selection rule, deployment note)."""
    sensors = ml_sensor_keys(registry)
    if not sensors:
        raise TrainingError("No ML sensors: no sensor has enabled AND include_in_ml in sensors.json")
    names = feature_names(sensors, stats if stats is not None else ml_stats(registry))
    X, info = build_training_matrix(dataset, sensors, window_s, max_missing_frac, names)
    if len(X) < MIN_WINDOWS:
        raise TrainingError(f"Only {len(X)} normal windows (need at least {MIN_WINDOWS}). "
                            "Record or generate more label=normal data.")

    model = IsolationForest(n_estimators=n_estimators, contamination=contamination,
                            random_state=random_state)
    model.fit(X)
    scores = model.score_samples(X)
    cal = calibrate(scores, model.offset_)

    health = np.array([health_from_score(s, cal) for s in scores])
    n_real, n_syn = info["rows_normal_by_source"]["real"], info["rows_normal_by_source"]["synthetic"]
    synthetic_used = n_syn > 0
    meta: dict[str, Any] = {
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model_type": "IsolationForest",
        "params": {"n_estimators": n_estimators, "contamination": contamination, "random_state": random_state},
        "sklearn_version": sklearn.__version__,
        "python_version": platform.python_version(),
        "sensors": sensors,
        "feature_names": names,
        "window_s": window_s,
        "max_missing_frac": max_missing_frac,
        "trained_on": {"real_rows": n_real, "synthetic_rows": n_syn, "sessions": list(sessions or [])},
        "status": default_status(n_real, n_syn, sessions),
        "training": {
            "files": [Path(f).name for f in dataset.files],
            "windows": int(len(X)),
            **info,
        },
        "calibration": cal,
        "training_score_quantiles": {q: float(np.quantile(scores, float(q) / 100))
                                     for q in ("1", "5", "50", "95", "99")},
        "training_health": {"share_below_50": float((health < 50).mean()),
                            "p5": float(np.quantile(health, 0.05)), "median": float(np.median(health))},
        "normal_stats": {n: {"mean": float(X[:, i].mean()), "std": max(float(X[:, i].std()), STD_FLOOR),
                             "min": float(X[:, i].min()), "max": float(X[:, i].max())}
                         for i, n in enumerate(names)},
        "range_excess": RANGE_EXCESS_META,
        "provisional": synthetic_used,
        "provisional_reason": ("trained on synthetic data; retrain on real normal recordings (Phase 8)"
                               if synthetic_used else None),
    }
    meta.update(extra_meta or {})
    return model, meta


def default_status(n_real: int, n_syn: int, sessions: list[str] | None) -> str:
    """One plain line for the dashboard: what the model was trained on."""
    where = f" ({', '.join(sessions)})" if sessions else ""
    if n_real and n_syn:
        return f"trained on real{where} + synthetic normal data"
    if n_real:
        return f"trained on real normal data{where}"
    return "provisional: trained on simulated data only"


def save(model: IsolationForest, meta: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.joblib"
    meta_path = out_dir / "model_meta.json"
    joblib.dump(model, model_path)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return model_path, meta_path
