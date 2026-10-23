"""Generate synthetic recordings for ML training (normal) and development checks (faults).

    python scripts/generate_synthetic.py                       # 60 min normal + dev fault set
    python scripts/generate_synthetic.py --minutes 120 --sessions 8
    python scripts/generate_synthetic.py --from-real ../data/recordings/session_*.csv

Output (data/synthetic/, not in git; this script is the source of truth):
    normal_sNN.csv            label=normal, source=synthetic, for TRAINING
    devfault_<scenario>_sNN.csv  labelled fault scenarios, for DEVELOPMENT CHECKS ONLY
                              (evaluate.py refuses them without --dev-synthetic)

Each normal session uses a different seed and a shifted baseline (--jitter), so the
model does not learn one exact operating point. --from-real replaces the per-sensor
baselines in sim_profile.json with statistics of real label=normal rows (Phase 8).
"""
from __future__ import annotations

import argparse
import copy
import csv
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.config import ROOT_DIR, load_settings  # noqa: E402
from app.ml import dataset  # noqa: E402
from app.models import ParseStats, csv_header  # noqa: E402
from app.registry import Registry  # noqa: E402
from app.sources.simulator import SimulatorSource, load_profile  # noqa: E402

OUT_DIR = ROOT_DIR / "data" / "synthetic"
DEV_FAULTS = {  # scenario -> seconds to simulate
    "sudden_fault": 120, "slow_drift": 300, "recovery": 90, "drift_and_recover": 420, "sensor_fault": 120,
}


def profile_from_real(profile: dict, patterns: list[str], registry: Registry) -> dict:
    """Replace per-sensor baselines with stats from real label=normal rows."""
    data = dataset.load(patterns, registry)
    rows = [r for r in data.rows if r.source == "real" and r.label == "normal"]
    if not rows:
        sys.exit(f"--from-real: no rows with source=real and label=normal in {data.files or patterns}")
    prof = copy.deepcopy(profile)
    for key, cfg in prof["sensors"].items():
        vals = np.array([r.values[key] for r in rows if r.values.get(key) is not None], dtype=float)
        if len(vals) < 30:
            print(f"  {key}: only {len(vals)} real values, keeping sim_profile.json baseline")
            continue
        std = float(vals.std())
        # Split the real spread between slow wander and fast noise (approximate, see docstring).
        cfg.update(mean=float(vals.mean()), wander=0.8 * std, noise=0.6 * std,
                   min=float(np.percentile(vals, 1)), max=float(np.percentile(vals, 99)))
        print(f"  {key}: mean {cfg['mean']:.2f}, std {std:.2f}, range {cfg['min']:.2f}..{cfg['max']:.2f} "
              f"from {len(vals)} real rows")
    return prof


def jittered(profile: dict, rng: random.Random, jitter: float) -> dict:
    """Shift each sensor's baseline by up to +/- jitter * half its normal range."""
    prof = copy.deepcopy(profile)
    for cfg in prof["sensors"].values():
        shift = rng.uniform(-1, 1) * jitter * (cfg["max"] - cfg["min"]) / 2
        lo, hi = cfg.get("physical_min", -1e9), cfg.get("physical_max", 1e9)
        for k in ("mean", "min", "max"):
            cfg[k] = min(max(cfg[k] + shift, lo), hi)
    return prof


def write_session(path: Path, registry: Registry, profile: dict, scenario: str, seconds: int,
                  seed: int, start: datetime, hold_seconds: int) -> int:
    sim = SimulatorSource(registry=registry, stats=ParseStats(), scenario=scenario, profile=profile,
                          seed=seed, hold_seconds=hold_seconds)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(csv_header(registry))
        for _ in range(seconds):
            row = sim.make_row()
            row.ts_iso = (start + timedelta(milliseconds=row.ms)).isoformat(timespec="milliseconds")
            w.writerow(row.to_csv_row(registry))
            sim.elapsed_s += sim.tick_s
    return seconds


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=60, help="total minutes of normal data (default 60)")
    ap.add_argument("--sessions", type=int, default=6, help="number of normal sessions/seeds (default 6)")
    ap.add_argument("--seed", type=int, default=1000, help="first seed (default 1000)")
    ap.add_argument("--jitter", type=float, default=0.3, help="baseline shift per session, 0..1 (default 0.3)")
    ap.add_argument("--fault-seeds", type=int, default=3, help="dev fault recordings per scenario (0 = none)")
    ap.add_argument("--from-real", nargs="+", metavar="CSV", help="take baselines from real normal recordings")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)

    registry = Registry.load()
    settings = load_settings()
    profile = load_profile()
    if args.from_real:
        print("Baselines from real data:")
        profile = profile_from_real(profile, args.from_real, registry)
    args.out.mkdir(parents=True, exist_ok=True)
    for old in list(args.out.glob("normal_s*.csv")) + list(args.out.glob("devfault_*.csv")):
        old.unlink()

    base = datetime(2026, 1, 1).astimezone()
    per_session = int(round(args.minutes * 60 / args.sessions))
    total = 0
    for i in range(args.sessions):
        seed = args.seed + i
        prof = jittered(profile, random.Random(seed), args.jitter)
        total += write_session(args.out / f"normal_s{i:02d}.csv", registry, prof, "normal", per_session,
                               seed, base + timedelta(days=i), settings.hold_seconds)
    print(f"normal: {args.sessions} sessions x {per_session} s = {total} rows ({total / 60:.0f} min) -> {args.out}")

    n_fault = 0
    for scenario, seconds in DEV_FAULTS.items():
        if scenario not in profile["scenarios"]:
            continue
        for k in range(args.fault_seeds):
            seed = args.seed + 500 + k
            write_session(args.out / f"devfault_{scenario}_s{k:02d}.csv", registry, profile, scenario,
                          seconds, seed, base + timedelta(days=100 + n_fault), settings.hold_seconds)
            n_fault += 1
    if n_fault:
        print(f"dev faults: {n_fault} files (DEVELOPMENT CHECKS ONLY, never results)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
