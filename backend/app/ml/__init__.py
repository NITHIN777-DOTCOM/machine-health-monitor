"""ML engine: window features, IsolationForest scoring, trend forecast, evaluation.

Data rules (enforced in code):
- Training uses only label=normal rows (training.py). Synthetic rows may be used for
  training only, and make the model "provisional".
- Evaluation numbers are only valid on REAL rows with induced faults (evaluation.py
  refuses otherwise; --dev-synthetic output is stamped "SIMULATED DATA - NOT A RESULT").
- ML features come only from registry sensors with enabled AND include_in_ml.
"""
