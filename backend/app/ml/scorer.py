"""Live anomaly scoring with a trained model (models/model.joblib + model_meta.json).

Never crashes the backend: a missing or broken model gives NO_MODEL, and a model trained
on a different set of ML sensors gives NEEDS_RETRAIN. In both cases ML is off and the
device rules keep working.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import sklearn

from ..config import MODELS_DIR
from ..registry import Registry
from .features import FeatureWindow, ml_sensor_keys, split_feature, to_vector

log = logging.getLogger(__name__)

OK, ANOMALY, WARMING_UP, NO_MODEL, NEEDS_RETRAIN = "OK", "ANOMALY", "WARMING_UP", "NO_MODEL", "NEEDS_RETRAIN"
Z_CAP = 99.0

# How to describe a feature that is far from normal, by statistic and sign of z.
_WORDS = {
    "mean": ("high", "low"), "last": ("high", "low"), "max": ("high", "low"), "min": ("high", "low"),
    "std": ("unstable", "unusually steady"), "slope": ("rising", "falling"),
}

# Plain-language bands of |z| (DATA_CONTRACT.md section 9). The dashboard's
# lib/format.ts causeWords() uses the same table.
Z_BANDS = ((6.0, "far"), (3.0, "clear"), (2.0, "slight"))
_PLAIN = {   # stat kind -> sign -> band -> words
    "level": {1: {"slight": "slightly high", "clear": "above normal", "far": "far above normal"},
              -1: {"slight": "slightly low", "clear": "below normal", "far": "far below normal"}},
    "std": {1: {"slight": "slightly unstable", "clear": "unstable", "far": "very unstable"},
            -1: {"slight": "slightly steady", "clear": "unusually steady", "far": "unusually steady"}},
    "slope": {1: {"slight": "rising slightly", "clear": "rising", "far": "rising fast"},
              -1: {"slight": "falling slightly", "clear": "falling", "far": "falling fast"}},
}


def z_band(z: float) -> str:
    """|z| < 2 normal, 2-3 slight, 3-6 clear, >= 6 far."""
    return next((band for limit, band in Z_BANDS if abs(z) >= limit), "normal")


def plain_words(stat: str, z: float) -> str:
    """"far above normal", "slightly unstable", "rising", "normal", ..."""
    band = z_band(z)
    if band == "normal":
        return "normal"
    kind = stat if stat in ("std", "slope") else "level"
    return _PLAIN[kind][1 if z >= 0 else -1][band]


def short_name(display_name: str) -> str:
    """"Sound level (peak deviation)" -> "Sound level": the name without its explanation."""
    return re.sub(r"\s*\(.*?\)", "", display_name).strip() or display_name


# Range term defaults (training.py writes them into model_meta.json "range_excess").
RANGE_K = 16.7    # health points per e-fold of (1 + excess / RANGE_B)
RANGE_B = 0.28    # excess (training stds) at which the log curve starts to bend


def if_health(score: float, cal: Mapping[str, float]) -> float:
    """IsolationForest part, 0..100. Linear from 100 (median normal score) to 50 (the
    decision threshold); below the threshold it decays softly as 50 / (1 + d), d = distance
    below the threshold in units of (median - threshold): 1 -> 25, 3 -> 12.5. IF scores
    saturate outside the training data, so this part alone never claims "0"."""
    t, m = cal["threshold_score"], cal["median_score"]
    r = (score - t) / (m - t)
    return float(min(100.0, 50.0 + 50.0 * r)) if r >= 0 else float(50.0 / (1.0 - r))


def range_health(excess: float, k: float = RANGE_K, b: float = RANGE_B) -> float:
    """Range part, 0..100: 100 inside the training range, then a log curve so moderately
    out-of-range values give a mid score and only extreme ones reach 0.
    excess 1.4 -> 70, 2.6 -> 61, 6.4 -> 47, 13.8 -> 35, 24 -> 26, 39 -> 18, 89 -> 4, >= 120 -> 0."""
    return float(min(100.0, max(0.0, 100.0 - k * float(np.log1p(max(0.0, excess) / b)))))


def raw_health(score: float, cal: Mapping[str, float], excess: float = 0.0,
               k: float = RANGE_K, b: float = RANGE_B) -> float:
    """Health 0..100; below 50 means anomaly. The worse of the two parts."""
    return min(if_health(score, cal), range_health(excess, k, b))


def health_from_score(score: float, cal: Mapping[str, float], excess: float = 0.0,
                      k: float = RANGE_K, b: float = RANGE_B) -> float:
    """0..100: 100 at the median normal score, 50 at the decision threshold, then a soft
    decay; the range term pulls it further down for values outside the training range."""
    return float(min(100.0, max(0.0, raw_health(score, cal, excess, k, b))))


class Scorer:
    def __init__(self, registry: Registry, model: Any = None, meta: dict[str, Any] | None = None,
                 error: str | None = None):
        self.registry = registry
        self.model = model
        self.meta = meta or {}
        self.status = "READY"
        self.message: str | None = None
        if model is None or meta is None:
            self.status, self.message = NO_MODEL, error or "no trained model (run scripts/train.py)"
            return
        current = ml_sensor_keys(registry)
        trained = list(self.meta.get("sensors", []))
        if current != trained:
            self.status = NEEDS_RETRAIN
            self.message = (f"model needs retrain (sensors changed): model uses {trained}, "
                            f"registry ML sensors are {current}")
            log.warning(self.message)
            return
        n_in = getattr(model, "n_features_in_", None)
        if n_in is not None and n_in != len(self.meta.get("feature_names", [])):
            self.status = NEEDS_RETRAIN
            self.message = "model needs retrain (feature count does not match model_meta.json)"
            log.warning(self.message)
            return
        if self.meta.get("sklearn_version") != sklearn.__version__:
            log.warning("Model trained with scikit-learn %s, running %s",
                        self.meta.get("sklearn_version"), sklearn.__version__)

    @classmethod
    def load(cls, registry: Registry, model_dir: Path = MODELS_DIR) -> "Scorer":
        model_path, meta_path = model_dir / "model.joblib", model_dir / "model_meta.json"
        if not model_path.exists() or not meta_path.exists():
            return cls(registry, error=f"no trained model in {model_dir} (run scripts/train.py)")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            model = joblib.load(model_path)
        except Exception as exc:  # noqa: BLE001 - a broken model file must not stop the backend
            log.error("Could not load model from %s: %s", model_dir, exc)
            return cls(registry, error=f"could not load model: {exc}")
        return cls(registry, model, meta)

    @property
    def ready(self) -> bool:
        return self.status == "READY"

    @property
    def provisional(self) -> bool:
        return bool(self.meta.get("provisional", False))

    def make_window(self) -> FeatureWindow | None:
        """A FeatureWindow with the model's own window settings (None if ML is off)."""
        if not self.ready:
            return None
        return FeatureWindow(self.meta["sensors"], self.meta["window_s"], self.meta["max_missing_frac"])

    def _result(self, status: str, **extra: Any) -> dict[str, Any]:
        return {"ml_status": status, "health": None, "range_excess": None, "causes": [],
                "provisional": self.provisional, "score": None, "message": self.message, **extra}

    def score(self, features: Mapping[str, float] | None) -> dict[str, Any]:
        if not self.ready:
            return self._result(self.status)
        if features is None:
            return self._result(WARMING_UP, message="collecting a full window of data")
        names = self.meta["feature_names"]
        s = float(self.model.score_samples(to_vector(features, names))[0])
        cal = self.meta["calibration"]
        excess = self.range_excess(features)
        rx = self.meta.get("range_excess", {})
        raw = raw_health(s, cal, excess, rx.get("k", RANGE_K), rx.get("b", RANGE_B))
        status = ANOMALY if raw < 50.0 else OK
        return {
            "ml_status": status,
            "health": round(min(100.0, max(0.0, raw)), 1),
            "range_excess": round(excess, 2),
            "causes": self.causes(features),
            "provisional": self.provisional,
            "score": s,
            "message": None,
        }

    def range_excess(self, features: Mapping[str, float]) -> float:
        """Largest distance beyond the training min/max, in training standard deviations."""
        worst = 0.0
        for name, value in features.items():
            st = self.meta["normal_stats"].get(name)
            if st is None or "min" not in st:
                continue
            beyond = max(0.0, value - st["max"], st["min"] - value)
            worst = max(worst, beyond / st["std"])
        return worst

    def causes(self, features: Mapping[str, float], top: int = 2) -> list[dict[str, Any]]:
        """The `top` sensors whose features are furthest from normal (largest |z|).

        Per sensor, a level feature (mean/last/min/max) that is itself unusual (|z| >= 2)
        wins over a larger std or slope z: "Vibration: far above normal" says more to a
        newcomer than "Vibration: very unstable" for the same fault."""
        stats = self.meta["normal_stats"]
        best: dict[str, tuple[float, str]] = {}
        best_level: dict[str, tuple[float, str]] = {}
        for name, value in features.items():
            st = stats.get(name)
            if st is None:
                continue
            z = float(np.clip((value - st["mean"]) / st["std"], -Z_CAP, Z_CAP))
            key, stat = split_feature(name)
            if key not in best or abs(z) > abs(best[key][0]):
                best[key] = (z, name)
            if stat not in ("std", "slope") and (key not in best_level or abs(z) > abs(best_level[key][0])):
                best_level[key] = (z, name)
        for key, (z, name) in best_level.items():
            if z_band(z) != "normal":
                best[key] = (z, name)
        ranked = sorted(best.items(), key=lambda kv: -abs(kv[1][0]))[:top]
        out = []
        for key, (z, name) in ranked:
            stat = split_feature(name)[1]
            word = _WORDS.get(stat, ("high", "low"))[0 if z >= 0 else 1]
            sensor = self.registry.get(key)
            display = sensor.display_name if sensor else key
            out.append({"sensor": key, "feature": name, "z": round(z, 2), "direction": word,
                        "band": z_band(z), "text": f"{short_name(display)}: {plain_words(stat, z)}"})
        return out

    def info(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "provisional": self.provisional,
            "sensors": self.meta.get("sensors"),
            "window_s": self.meta.get("window_s"),
            "created": self.meta.get("created"),
        }
