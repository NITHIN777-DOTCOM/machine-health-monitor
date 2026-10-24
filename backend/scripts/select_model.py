"""Phase 8.2 model selection: two candidates, validated on session 01 only, then the final fit.

    python scripts/select_model.py                       # compare, pick, fit, save to models/
    python scripts/select_model.py --out ../build/m      # same, saved elsewhere

DATA (data/recordings/MANIFEST.json; the roles are checked in code):
  training     session 01 (role "train"), its cleaned label=normal rows only
  validation   the LAST 20 % (by time) of session 01's normal rows, never trained on, plus ALL
               of session 01's fault rows (the model learns normal only, so it never sees them)
  session 02   (role "test") is not read by this script; nothing here can depend on it

CANDIDATES
  (a) real    the training split of session 01's normal rows
  (b) mixed   (a) + synthetic normal data from generate_synthetic.py --from-real, with the
              baselines taken from the same training split (generator defaults: 60 min,
              6 sessions, jitter 0.3, first seed 1000)
Both use the shipped settings: IsolationForest, 200 trees, contamination 0.01, seed 42,
10 s window, health/range calibration as in training.py.

Both are scored on the validation rows through the LIVE pipeline (evaluation.run: device-rule
mirror, smoothed ML, forecast), so the numbers are what the dashboard would have shown.

SELECTION RULE (fixed before any candidate was trained or scored):
  FA  = validation false-alarm rate: held-out normal rows, outside the 15 s after-fault
        margin, on which the smoothed ML status is ANOMALY
  DET = validation detection rate: session 01 fault rows on which the smoothed ML status
        is ANOMALY
  1. A candidate is acceptable if FA <= 2 %.
  2. Both acceptable: the higher DET wins; if DET differs by less than 2 percentage
     points, (a) wins (simpler: no assumptions from the simulator).
  3. Only one acceptable: that one.
  4. Neither acceptable: the lower FA wins, and the calibration is reviewed (step B4).

CALIBRATION CHECK (B4), on the held-out normal rows with the chosen candidate:
  median health >= 90 and at most 2 % of the scored rows below the anomaly level (50).
  If it fails, a change is made only from validation numbers and is recorded in the
  output (--contamination is the knob; every run writes what it used).

B4 REVIEW (added 2026-10-24 AFTER the first run; the rule above is unchanged):
  First run (all 24 features): FA (a) 124/170, (b) 156/170: neither acceptable, (a) by
  step 4. Calibration check failed (median 53.5, 19.5 % below 50). Diagnosis on the
  validation rows: the held-out minutes are warmer (to 31.3 C) and drier (to 71 %RH) than
  the training minutes, so the temperature/humidity LEVEL features fall outside the
  training range and the range term pulls health to 50-60, where the smoothing latches
  ANOMALY. --contamination cannot fix that (0.005 gave identical numbers). Change, from
  validation only: temperature and humidity enter the model by their change (std, slope),
  not their level (sensors.json "ml_stats"); the temperature level stays with the rules and
  the forecast. Re-run of BOTH candidates with that feature set, same rule. Remaining flags
  on held-out normal are table bumps (vibration 13-40) left in session 01's normal labels
  and the cool-down after its temperature fault: not calibrated away, because accepting
  vibration 13-40 as normal would blind the model to subtle vibration. Numbers of the first
  run and the variants: docs/eval/phase8_b4_review.json.

FINAL FIT: the chosen recipe refit on ALL of session 01's normal rows (the 20 % holdout
included: it holds the session's warmest, driest minutes, which the shipped model should
know). The validation numbers describe the 80 % fit; the final test (session 02,
scripts/evaluate.py) describes the shipped model.

Writes <out>/model.joblib + model_meta.json and docs/eval/phase8_validation.json (the
comparison, the rule, the choice, the calibration check).
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

import generate_synthetic as gen  # noqa: E402
from app.config import MODELS_DIR, ROOT_DIR, load_settings  # noqa: E402
from app.ml import dataset, evaluation, roles, training  # noqa: E402
from app.ml.features import ml_stats  # noqa: E402
from app.ml.scorer import Scorer  # noqa: E402
from app.paths import MANIFEST_FILE, RECORDINGS_DIR  # noqa: E402
from app.registry import Registry  # noqa: E402
from app.sources.simulator import load_profile  # noqa: E402

TRAIN_SESSION = "real_session_01_20261024.csv"
HOLDOUT_FRAC = 0.2
SYN_DIR = ROOT_DIR / "data" / "synthetic"
REPORT = ROOT_DIR / "docs" / "eval" / "phase8_validation.json"
FA_MAX, DET_TIE, MEDIAN_MIN, BELOW_MAX = 0.02, 0.02, 90.0, 0.02
STATUS = "bench-trained on real data (session 01)"
DEPLOYMENT_NOTE = "trained on a bench setup; a real machine needs its own normal data and a retrain"
RULE = ("FA = held-out normal rows (outside the 15 s after-fault margin) flagged ANOMALY by the smoothed ML; "
        "DET = session 01 fault rows flagged ANOMALY. 1) acceptable if FA <= 2 %. 2) both acceptable: higher DET "
        "wins, (a) real-only if DET differs by < 2 points. 3) one acceptable: that one. 4) neither: lower FA, "
        "then review the calibration. Fixed before any candidate was trained.")


def synthetic_normal(rows: list, out: Path, registry: Registry, hold_seconds: int,
                     minutes: float = 60, sessions: int = 6, jitter: float = 0.3, seed: int = 1000) -> list[str]:
    """generate_synthetic.py --from-real, on the given rows only (normal sessions, no faults)."""
    profile = gen.profile_from_rows(load_profile(), rows, where="the training split")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    base = datetime(2026, 1, 1).astimezone()
    per = int(round(minutes * 60 / sessions))
    files = []
    for i in range(sessions):
        prof = gen.jittered(profile, random.Random(seed + i), jitter)
        path = out / f"normal_s{i:02d}.csv"
        gen.write_session(path, registry, prof, "normal", per, seed + i, base + timedelta(days=i), hold_seconds)
        files.append(str(path))
    return files


def validate(model, meta, val: dataset.Dataset, registry: Registry, settings) -> dict:
    """Live-pipeline evaluation of one candidate on the validation rows."""
    scorer = Scorer(registry, model, meta)
    res = evaluation.run(val, registry, scorer, settings)
    m = res["metrics"]["ml"]
    normal = [t for t in res["trace"] if t["label"] == "normal" and t["window_full"]]
    health = np.array([t["health"] for t in normal if t["health"] is not None], dtype=float)
    rules = res["metrics"]["rules"]
    # Diagnostic only (not in the rule): held-out normal rows whose whole window is quiet
    # (vibration and sound < 10, session 02's definition of undisturbed normal).
    tr = res["trace"]
    quiet = [t for i, t in enumerate(tr) if t["label"] == "normal" and t["window_full"] and t["after_fault_s"] is not None
             and t["after_fault_s"] > res["margin_s"]
             and all((u["values"].get("vib_count") or 0) < 10 and (u["values"].get("sound_peak") or 0) < 10
                     for u in tr[max(0, i - 9):i + 1])]
    beyond = [t for t in res["trace"] if t["label"] == "fault" and t["window_full"] and not t["flags"]["rules"]]
    return {
        "false_alarms": {"rows": m["normal_flagged"], "of": m["normal"], "rate": m["false_alarm_rate"],
                         "raw_rows": m["normal_raw_flagged"], "raw_of": m["normal_raw"], "raw_rate": m["false_alarm_rate_raw"]},
        "detection": {"rows": m["fault_flagged"], "of": m["fault"], "rate": m["detection_rate"],
                      "episodes": m["episodes_detected"], "of_episodes": m["episodes"], "mean_delay_s": m["mean_delay_s"]},
        "false_alarms_quiet_normal": {"rows": sum(t["flags"]["ml"] for t in quiet), "of": len(quiet)},
        "rules_detection": {"rows": rules["fault_flagged"], "of": rules["fault"], "rate": rules["detection_rate"]},
        "ml_on_fault_rows_rules_missed": {"rows": sum(t["flags"]["ml"] for t in beyond), "of": len(beyond)},
        "health_on_heldout_normal": {
            "rows": int(len(health)), "median": float(np.median(health)), "p5": float(np.percentile(health, 5)),
            "min": float(health.min()), "share_below_50": float((health < 50).mean()),
            "share_below_60": float((health < 60).mean())},
    }


def choose(results: dict[str, dict]) -> tuple[str, str]:
    """The pre-stated rule. Returns (candidate, why)."""
    fa = {k: r["false_alarms"]["rate"] for k, r in results.items()}
    det = {k: r["detection"]["rate"] or 0.0 for k, r in results.items()}
    ok = [k for k in ("a", "b") if fa[k] is not None and fa[k] <= FA_MAX]
    if len(ok) == 2:
        if abs(det["a"] - det["b"]) < DET_TIE:
            return "a", f"both FA <= {FA_MAX:.0%}; DET within {DET_TIE * 100:.0f} points, so (a) (simpler)"
        win = max(ok, key=lambda k: det[k])
        return win, f"both FA <= {FA_MAX:.0%}; ({win}) has the higher DET"
    if len(ok) == 1:
        return ok[0], f"only ({ok[0]}) has FA <= {FA_MAX:.0%}"
    win = min(("a", "b"), key=lambda k: fa[k])
    return win, f"neither has FA <= {FA_MAX:.0%}; ({win}) has the lower FA; calibration reviewed"


def calibration_check(r: dict) -> dict:
    h = r["health_on_heldout_normal"]
    return {"median_health": h["median"], "share_below_50": h["share_below_50"],
            "target": f"median >= {MEDIAN_MIN:.0f} and <= {BELOW_MAX:.0%} below 50",
            "passed": h["median"] >= MEDIAN_MIN and h["share_below_50"] <= BELOW_MAX}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=MODELS_DIR)
    ap.add_argument("--report", type=Path, default=REPORT)
    ap.add_argument("--contamination", type=float, default=0.01, help="B4 knob (default 0.01, the shipped value)")
    ap.add_argument("--n-estimators", type=int, default=200)
    args = ap.parse_args(argv)

    settings, registry = load_settings(), Registry.load()
    manifest = roles.Manifest.load(MANIFEST_FILE)
    path = RECORDINGS_DIR / TRAIN_SESSION
    data = dataset.load([str(path)], registry)
    roles.check_training([path], data.real_by_file(), manifest, strict=True)     # raises for a non-train file
    train_split, val, split = dataset.holdout_last_normal(data, HOLDOUT_FRAC)
    split_rows = [r for r in train_split.rows if r.label == "normal"]
    print(f"session 01: {len(data.rows)} rows; training split {split['train_normal_rows']} normal rows, "
          f"validation {split['holdout_normal_rows']} normal rows (from {split['holdout_from']}) "
          f"+ {data.counts()['label'].get('fault', 0)} fault rows")
    params = dict(window_s=settings.ml_window_s, max_missing_frac=settings.ml_max_missing_frac,
                  n_estimators=args.n_estimators, contamination=args.contamination, random_state=42,
                  sessions=[TRAIN_SESSION])

    syn_files = synthetic_normal(split_rows, SYN_DIR / "from_real_s01_split", registry, settings.hold_seconds)
    syn = dataset.load(syn_files, registry)
    cands = {"a": train_split,
             "b": dataset.Dataset(train_split.files + syn.files, train_split.segments + syn.segments)}
    results, sizes = {}, {}
    for k, d in cands.items():
        model, meta = training.train(d, registry, **params)
        sizes[k] = {**meta["trained_on"], "windows": meta["training"]["windows"]}
        results[k] = validate(model, meta, val, registry, settings)
        r = results[k]
        print(f"({k}) trained on {sizes[k]['real_rows']} real + {sizes[k]['synthetic_rows']} synthetic rows: "
              f"FA {r['false_alarms']['rows']}/{r['false_alarms']['of']}  DET {r['detection']['rows']}/{r['detection']['of']} "
              f"(episodes {r['detection']['episodes']}/{r['detection']['of_episodes']})  "
              f"[FA on quiet normal {r['false_alarms_quiet_normal']['rows']}/{r['false_alarms_quiet_normal']['of']}]  "
              f"health on held-out normal: median {r['health_on_heldout_normal']['median']:.1f}, "
              f"{r['health_on_heldout_normal']['share_below_50']:.1%} below 50")
    chosen, why = choose(results)
    calib = calibration_check(results[chosen])
    print(f"chosen: ({chosen}): {why}")
    print(f"calibration check: median {calib['median_health']:.1f}, {calib['share_below_50']:.1%} below 50 -> "
          f"{'passed' if calib['passed'] else 'FAILED'} ({calib['target']})")

    # Final fit: the chosen recipe on all of session 01's normal rows.
    final_data = data
    if chosen == "b":
        all_normal = [r for r in data.rows if r.label == "normal"]
        f_syn = dataset.load(synthetic_normal(all_normal, SYN_DIR / "from_real_s01_all", registry,
                                              settings.hold_seconds), registry)
        final_data = dataset.Dataset(data.files + f_syn.files, data.segments + f_syn.segments)
    selection = {"rule": RULE, "chosen": chosen, "why": why, "contamination": args.contamination,
                 "ml_stats": ml_stats(registry), "feature_count": None,
                 "validation": {k: {"trained_on": sizes[k], **results[k]} for k in results},
                 "calibration_check": calib}
    model, meta = training.train(final_data, registry, **{**params, "extra_meta": {
        "status": STATUS, "deployment_note": DEPLOYMENT_NOTE, "provisional": False, "provisional_reason": None,
        "candidate": {"a": "real normal only", "b": "real + synthetic normal (--from-real)"}[chosen],
        "selection": {"rule": RULE, "chosen": chosen, "why": why, "validation_split": split,
                      "calibration_check": calib, "ml_stats": ml_stats(registry),
                      "validation": {k: {"false_alarms": results[k]["false_alarms"], "detection": results[k]["detection"]}
                                     for k in results}}}})
    selection["feature_count"] = len(meta["feature_names"])
    training.save(model, meta, args.out)
    print(f"final model: {meta['trained_on']}, {meta['training']['windows']} windows -> {args.out}")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({
        "created": meta["created"], "split": split, "final_trained_on": meta["trained_on"],
        "params": params | {"sessions": [TRAIN_SESSION]}, **selection}, indent=2) + "\n", encoding="utf-8")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
