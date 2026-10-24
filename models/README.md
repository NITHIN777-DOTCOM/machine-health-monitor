# Models

> **BENCH-TRAINED MODEL.** `model.joblib` is trained on the 868 real `normal` rows of
> session 01 (`data/recordings/real_session_01_20261024.csv`, role `train`), no synthetic
> data (`"provisional": false`). It was chosen on session 01 validation rows by a rule fixed
> beforehand and tested **once** on the held-out session 02:
> [`docs/eval/eval_real_session_02.md`](../docs/eval/eval_real_session_02.md).
> It knows the demo bench only: **a real machine needs its own normal data and a retrain.**

| File | Contents |
|---|---|
| `model.joblib` | scikit-learn `IsolationForest` (200 trees, contamination 0.01, random_state 42), 16 features: sound and vibration mean/std/min/max/slope/last, temperature and humidity std/slope only (`ml_stats` in sensors.json) |
| `model_meta.json` | Everything needed to use and audit the model: sensors and feature names, window, training files and row counts by source (real/synthetic), training date, scikit-learn version, health calibration, per-feature normal statistics, `provisional` flag |

## How it was made

```
cd backend
python scripts/select_model.py      # candidates (a) real / (b) real + synthetic on session 01,
                                    # the pre-stated rule, calibration check, final fit -> models/
python scripts/evaluate.py ../data/recordings/real_session_02_test_20261024.csv ...   # held-out test
```

`scripts/train.py` still trains a single model directly (e.g. on a new machine's normal
recordings); it accepts only `train` sessions (`data/recordings/MANIFEST.json`). Details of
the selection and the calibration check: [`docs/phase8_report.md`](../docs/phase8_report.md).

## Rules

- Training uses **only** `label=normal` rows of `train` sessions; `test` sessions are
  refused in code. Synthetic data may be used for training, and makes the model provisional.
- A change of `ml_stats` in sensors.json also needs a retrain (NEEDS_RETRAIN otherwise).
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
