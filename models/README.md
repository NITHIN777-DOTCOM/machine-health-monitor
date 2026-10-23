# Models

> **PROVISIONAL MODEL.** `model.joblib` is trained on **synthetic** data only
> (`"provisional": true` in `model_meta.json`). It exists so the software can be built
> and demonstrated. It says nothing about any real machine, and no accuracy figure may
> be quoted from it. It will be retrained on real normal recordings in Phase 8.

| File | Contents |
|---|---|
| `model.joblib` | scikit-learn `IsolationForest` (200 trees, contamination 0.01, random_state 42) |
| `model_meta.json` | Everything needed to use and audit the model: sensors and feature names, window, training files and row counts by source (real/synthetic), training date, scikit-learn version, health calibration, per-feature normal statistics, `provisional` flag |

## How it was made

```
cd backend
python scripts/generate_synthetic.py                  # 60 min normal data -> data/synthetic/
python scripts/train.py "../data/synthetic/normal_*.csv"
```

## Rules

- Training uses **only** `label=normal` rows. Synthetic data may be used for training,
  and makes the model provisional.
- The model's sensor list must match the registry's ML sensors (`enabled` AND
  `include_in_ml`). If a sensor is added or removed, the backend reports
  "model needs retrain (sensors changed)" and switches ML off; the device rules keep working.
- Retrain whenever the ML sensors, the feature window or the machine changes. See
  "Deployment on real machinery" in [`docs/DATA_CONTRACT.md`](../docs/DATA_CONTRACT.md#8-deployment-on-real-machinery).

## Health score

`health` (0–100) comes from the IsolationForest score, calibrated on the training windows:
100 at the median normal score, 50 at the model's decision threshold (below 50 =
ANOMALY), 0 at an equally large distance beyond the threshold. Because an
IsolationForest cannot tell *how far* outside the training range a value is, health is
also reduced by 50 points for every 3 training standard deviations that the most extreme
feature lies beyond its training min/max. Details: `backend/app/ml/training.py`.
