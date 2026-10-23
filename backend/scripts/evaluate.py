"""Evaluate ML vs the threshold rules (and the forecast) on labelled recordings.

    python scripts/evaluate.py ../data/recordings/session_*.csv
    python scripts/evaluate.py --dev-synthetic "../data/synthetic/devfault_*.csv"

By default only source=real rows are used, and the script refuses to run unless the
input contains real rows labelled "fault" (an induced, marked fault). --dev-synthetic
allows synthetic data for development checks; every output line and the report are then
stamped "SIMULATED DATA - NOT A RESULT".

Writes a markdown report to docs/eval/ (simulated reports get a _SIMULATED suffix).
Exit codes: 0 ok, 2 refused / bad input.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import MODELS_DIR, ROOT_DIR, load_settings  # noqa: E402
from app.ml import dataset, evaluation  # noqa: E402
from app.ml.scorer import Scorer  # noqa: E402
from app.registry import Registry  # noqa: E402

REPORT_DIR = ROOT_DIR / "docs" / "eval"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="labelled CSV recordings or globs")
    ap.add_argument("--dev-synthetic", action="store_true",
                    help="allow synthetic rows (development checks only; output stamped NOT A RESULT)")
    ap.add_argument("--model-dir", type=Path, default=MODELS_DIR)
    ap.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    ap.add_argument("--no-report", action="store_true", help="print only, do not write a report file")
    args = ap.parse_args(argv)
    sim = args.dev_synthetic

    def say(msg: str = "", err: bool = False) -> None:
        print(f"[{evaluation.STAMP}] {msg}" if sim else msg, file=sys.stderr if err else sys.stdout)

    registry = Registry.load()
    settings = load_settings()
    data = dataset.load(args.inputs, registry)
    if not data.files:
        say(f"No CSV files match {args.inputs}", err=True)
        return 2
    try:
        selected, notes = evaluation.select(data, allow_synthetic=sim)
    except evaluation.EvaluationRefused as exc:
        say(f"Evaluation refused: {exc}", err=True)
        return 2

    scorer = Scorer.load(registry, args.model_dir)
    counts = selected.counts()
    say(f"{len(data.files)} files; evaluating rows by source {counts['source']}, by label {counts['label']}")
    for n in notes:
        say(n)
    if scorer.ready and scorer.provisional:
        say("Model is PROVISIONAL (trained with synthetic data).")
    result = evaluation.run(selected, registry, scorer, settings)
    for line in evaluation.format_lines(result, simulated=sim):
        print(line)

    if not args.no_report:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        name = f"eval_{datetime.now():%Y%m%d_%H%M%S}{'_SIMULATED' if sim else ''}.md"
        path = args.out_dir / name
        path.write_text(evaluation.format_report(result, files=[Path(f).name for f in data.files], counts=counts,
                                                 notes=notes, model_info=scorer.info(), simulated=sim),
                        encoding="utf-8")
        say(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
