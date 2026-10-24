"""Make the SIMULATED demo recording shipped in the portable build (data/demo/).

    python scripts/make_demo_recording.py                  # -> data/demo/demo_SIMULATED_drift_recovery.csv
    python scripts/make_demo_recording.py --out "<folder>"

About 5 minutes on the device clock: 60 s normal, temperature drifts up past 32 C (WARNING)
and 35 C (CRITICAL), stays hot, cools back down (CRITICAL -> WARNING -> NORMAL with the hold
countdown), then 20 s normal. For replay and warm start on a laptop with no Arduino.
It is simulated data (source=synthetic): fine for a demo, never a result. Deterministic
(fixed seed and start time), so every build ships the same file.
"""
from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import paths  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.registry import Registry  # noqa: E402
from app.sources.simulator import load_profile  # noqa: E402
from generate_synthetic import write_session  # noqa: E402

NAME = "demo_SIMULATED_drift_recovery.csv"
SCENARIO = "demo_drift_recovery"
SECONDS = 310
START = datetime(2026, 1, 1, 10, 0, 0).astimezone()


def demo_profile() -> dict:
    """drift_and_recover from sim_profile.json, re-timed to fit 5 minutes."""
    profile = copy.deepcopy(load_profile())
    scen = copy.deepcopy(profile["scenarios"]["drift_and_recover"])
    scen.update(description="Demo: 60 s normal, temperature drift into CRITICAL, hot, cool-down, normal.",
                start_s=[60, 60], ramp_s=100, duration_s=150, recover_s=80)
    profile["scenarios"][SCENARIO] = scen
    return profile


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=paths.DEMO_DIR, help="output folder (default data/demo/)")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / NAME
    registry = Registry.load()
    write_session(path, registry, demo_profile(), SCENARIO, SECONDS, seed=6, start=START,
                  hold_seconds=load_settings().hold_seconds)
    states = [line.rstrip("\n").rsplit(",", 4)[1] for line in path.read_text(encoding="utf-8").splitlines()[1:]]
    seen = Counter(states)
    print(f"{path}: {len(states)} rows, dev_state rows {dict(seen)}")
    if seen["CRITICAL"] == 0 or states[-1] != "NORMAL":
        print("ERROR: the demo should reach CRITICAL and end NORMAL; check sim_profile.json", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
