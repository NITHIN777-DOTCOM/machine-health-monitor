"""Train the anomaly model on label=normal rows.

    python scripts/train.py "../data/synthetic/normal_*.csv"
    python scripts/train.py ../data/recordings/session_*.csv "../data/synthetic/normal_*.csv"

Only rows labelled "normal" are used (fault/unknown rows are skipped and break the
window). ML sensors come from config/sensors.json (enabled AND include_in_ml).
Writes models/model.joblib and models/model_meta.json. If any synthetic row was used
the model is marked "provisional": true.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import MODELS_DIR, load_settings  # noqa: E402
from app.ml import dataset, training  # noqa: E402
from app.registry import Registry  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="CSV files or globs (quote globs on Windows)")
    ap.add_argument("--out", type=Path, default=MODELS_DIR, help="output folder (default models/)")
    ap.add_argument("--n-estimators", type=int, default=200)
    ap.add_argument("--contamination", type=float, default=0.01)
    ap.add_argument("--random-state", type=int, default=42)
    args = ap.parse_args(argv)

    settings = load_settings()
    registry = Registry.load()
    data = dataset.load(args.inputs, registry)
    if not data.files:
        print(f"No CSV files match {args.inputs}", file=sys.stderr)
        return 2
    print(f"{len(data.files)} files, rows by source {data.counts()['source']}, by label {data.counts()['label']}")
    try:
        model, meta = training.train(data, registry, window_s=settings.ml_window_s,
                                     max_missing_frac=settings.ml_max_missing_frac,
                                     n_estimators=args.n_estimators, contamination=args.contamination,
                                     random_state=args.random_state)
    except training.TrainingError as exc:
        print(f"Training refused: {exc}", file=sys.stderr)
        return 2
    model_path, meta_path = training.save(model, meta, args.out)
    t = meta["training"]
    print(f"sensors: {meta['sensors']}  window: {meta['window_s']} s  features: {len(meta['feature_names'])}")
    print(f"normal rows used by source: {t['rows_normal_by_source']}  windows: {t['windows']}  "
          f"skipped (not normal): {t['rows_skipped_not_normal']}")
    cal = meta["calibration"]
    print(f"calibration: median {cal['median_score']:.4f} -> 100, threshold {cal['threshold_score']:.4f} -> 50, "
          f"abnormal {cal['abnormal_score']:.4f} -> 0;  training windows below 50: "
          f"{100 * meta['training_health']['share_below_50']:.1f}%")
    if meta["provisional"]:
        print("PROVISIONAL model: trained with synthetic data. Retrain on real normal recordings (Phase 8).")
    print(f"saved {model_path} and {meta_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
