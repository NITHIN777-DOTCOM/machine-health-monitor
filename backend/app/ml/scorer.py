"""Live anomaly scoring with a trained model (models/model.joblib + model_meta.json).

Never crashes the backend: a missing or broken model gives NO_MODEL, and a model trained
on a different set of ML sensors gives NEEDS_RETRAIN. In both cases ML is off and the
device rules keep working.
"""
from __future__ import annotations

import json
import logging
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


def raw_health(score: float, cal: Mapping[str, float], excess: float = 0.0, stds_per_50: float = 3.0) -> float:
    """Unclamped health; below 50 means anomaly. See training.py for the rules."""
    t, m = cal["threshold_score"], cal["median_score"]
    return 50.0 + 50.0 * (score - t) / (m - t) - 50.0 * excess / stds_per_50


def health_from_score(score: float, cal: Mapping[str, float], excess: float = 0.0, stds_per_50: float = 3.0) -> float:
    """0..100: 100 at the median normal score, 50 at the decision threshold, 0 beyond."""
    return float(min(100.0, max(0.0, raw_health(score, cal, excess, stds_per_50))))


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
        per50 = self.meta.get("range_excess", {}).get("stds_per_50_health", 3.0)
        raw = raw_health(s, cal, excess, per50)
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
        """The `top` sensors whose features are furthest from normal (largest |z|)."""
        stats = self.meta["normal_stats"]
        best: dict[str, tuple[float, str]] = {}
        for name, value in features.items():
            st = stats.get(name)
            if st is None:
                continue
            z = float(np.clip((value - st["mean"]) / st["std"], -Z_CAP, Z_CAP))
            key, _ = split_feature(name)
            if key not in best or abs(z) > abs(best[key][0]):
                best[key] = (z, name)
        ranked = sorted(best.items(), key=lambda kv: -abs(kv[1][0]))[:top]
        out = []
        for key, (z, name) in ranked:
            stat = split_feature(name)[1]
            word = _WORDS.get(stat, ("high", "low"))[0 if z >= 0 else 1]
            sensor = self.registry.get(key)
            display = sensor.display_name if sensor else key
            out.append({"sensor": key, "feature": name, "z": round(z, 2), "direction": word,
                        "text": f"{display} {word}"})
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
