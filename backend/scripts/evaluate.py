"""Evaluate ML vs the threshold rules (and the forecast) on labelled recordings.

    python scripts/evaluate.py ../data/recordings/session_*.csv
    python scripts/evaluate.py --dev-synthetic "../data/synthetic/devfault_*.csv"
    python scripts/evaluate.py ../data/recordings/real_session_02_test_20261024.csv \
        --steps ../data/recordings/raw/session_02_steps.tsv \
        --live-labels ../data/recordings/raw/raw_session_20261024_153633.csv \
        --json ../docs/eval/eval_real_session_02.json --md ../docs/eval/eval_real_session_02.md

By default only source=real rows are used, and the script refuses to run unless the
input contains real rows labelled "fault" (an induced, marked fault). --dev-synthetic
allows synthetic data for development checks; every output line and the report are then
stamped "SIMULATED DATA - NOT A RESULT".

DATA ROLES (data/recordings/MANIFEST.json, app/ml/roles.py): by default this computes
FINAL TEST numbers, so any "train" session (or a renamed copy of one) is refused: the
model has seen it. --validation is for choices during development (model selection,
calibration) and accepts ONLY "train" sessions, so the held-out test session cannot
influence a choice; its output is stamped VALIDATION. With --holdout-last FRAC only the
normal rows that train.py --holdout-last FRAC left out are counted as normal.

Every row runs through the live pipeline (device-rule mirror, smoothed ML, forecast).

Writes a markdown report to docs/eval/ (simulated reports get a _SIMULATED suffix).
With --steps (one real session): the per-step report (app/ml/session_report.py) for the
file's own labels AND, with --live-labels, the labels as set live (same rows, one pipeline
run), written to --json (for the dashboard) and --md.
Exit codes: 0 ok, 2 refused / bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import MODELS_DIR, ROOT_DIR, load_settings  # noqa: E402
from app.ml import dataset, evaluation, roles  # noqa: E402
from app.ml import session_report as session_report_mod  # noqa: E402
from app.paths import MANIFEST_FILE  # noqa: E402
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
    ap.add_argument("--validation", action="store_true",
                    help="validation on 'train' sessions only (not final test numbers)")
    ap.add_argument("--holdout-last", type=float, metavar="FRAC",
                    help="with --validation: count only the last FRAC of the normal rows (train.py's holdout)")
    ap.add_argument("--steps", type=Path, help="step log of ONE session: per-step report")
    ap.add_argument("--live-labels", type=Path, help="with --steps: the same session with its live labels (raw file)")
    ap.add_argument("--json", type=Path, help="with --steps: write the per-step report as JSON")
    ap.add_argument("--md", type=Path, help="with --steps: write the per-step report as markdown")
    ap.add_argument("--manifest", type=Path, default=MANIFEST_FILE, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.holdout_last and not args.validation:
        ap.error("--holdout-last needs --validation")
    sim = args.dev_synthetic

    def say(msg: str = "", err: bool = False) -> None:
        print(f"[{evaluation.STAMP}] {msg}" if sim else msg, file=sys.stderr if err else sys.stdout)

    registry = Registry.load()
    settings = load_settings()
    data = dataset.load(args.inputs, registry)
    if not data.files:
        say(f"No CSV files match {args.inputs}", err=True)
        return 2
    manifest = roles.Manifest.load(args.manifest)
    if args.steps and (len(data.files) != 1 or sim):
        say("--steps needs exactly one real recording", err=True)
        return 2
    extra = [args.live_labels] if args.live_labels else []
    try:
        role_notes = roles.check_evaluation([Path(f) for f in data.files] + extra, manifest,
                                            validation=args.validation)
    except roles.RoleError as exc:
        say(str(exc), err=True)
        return 2
    if args.holdout_last:
        _, data, split = dataset.holdout_last_normal(data, args.holdout_last)
        role_notes.append(f"validation normal rows: the last {args.holdout_last:.0%} ({split['holdout_normal_rows']} "
                          f"rows from {split['holdout_from']}); the earlier normal rows were trained on, not counted")
    try:
        selected, notes = evaluation.select(data, allow_synthetic=sim)
    except evaluation.EvaluationRefused as exc:
        say(f"Evaluation refused: {exc}", err=True)
        return 2
    notes = role_notes + notes

    scorer = Scorer.load(registry, args.model_dir)
    counts = selected.counts()
    say(f"{len(data.files)} files; evaluating rows by source {counts['source']}, by label {counts['label']}")
    for n in notes:
        say(n)
    if scorer.ready and scorer.provisional:
        say("Model is PROVISIONAL (trained with synthetic data).")
    result = evaluation.run(selected, registry, scorer, settings)
    for line in evaluation.format_lines(result, simulated=sim):
        print(f"[VALIDATION] {line}" if args.validation else line)

    if args.steps:
        return session_report(args, data, result, scorer, registry, manifest, say)

    if not args.no_report:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        kind = "_SIMULATED" if sim else "_VALIDATION" if args.validation else ""
        name = f"eval_{datetime.now():%Y%m%d_%H%M%S}{kind}.md"
        path = args.out_dir / name
        path.write_text(evaluation.format_report(result, files=[Path(f).name for f in data.files], counts=counts,
                                                 notes=notes, model_info=scorer.info(), simulated=sim),
                        encoding="utf-8")
        say(f"report: {path}")
    return 0


def session_report(args, data, result, scorer, registry, manifest, say) -> int:
    """Per-step report of one session, for its own labels and (optionally) its live labels."""
    cleaned = Path(data.files[0])
    fr = manifest.lookup(cleaned)
    label_sets = {"cleaned": [t["label"] for t in result["trace"]]}
    files = {"cleaned": cleaned.name, "steps": args.steps.name}
    if args.live_labels:
        lf = manifest.lookup(args.live_labels)
        if fr is None or lf is None or lf.session != fr.session:
            say(f"--live-labels {args.live_labels.name} is not a variant of the same session as {cleaned.name}", err=True)
            return 2
        live = session_report_mod.load_labels(args.live_labels)
        missing = [t["ms"] for t in result["trace"] if t["ms"] not in live]
        if missing:
            say(f"--live-labels: {len(missing)} rows of {cleaned.name} are not in {args.live_labels.name}", err=True)
            return 2
        label_sets["live"] = [live[t["ms"]] for t in result["trace"]]
        files["live"] = f"raw/{args.live_labels.name}"
    meta = scorer.meta if scorer.ready else {}
    model = {"status": meta.get("status", scorer.status), "created": meta.get("created"),
             "trained_on": meta.get("trained_on", {"real_rows": 0, "synthetic_rows": 0, "sessions": []}),
             "sensors": meta.get("sensors"), "feature_count": len(meta.get("feature_names", [])),
             "provisional": meta.get("provisional"), "deployment_note": meta.get("deployment_note")}
    rep = session_report_mod.build(result["trace"], session_report_mod.load_steps(args.steps), label_sets,
                                   meta.get("sensors") or [], result["margin_s"], session=fr.session if fr else cleaned.name,
                                   files=files, model=model)
    rep["subtle_text"] = session_report_mod.subtle_sentence(rep)
    for name, res in rep["label_sets"].items():
        say(f"[{name}] totals: {res['totals']}")
        for f in res["faults"]:
            say(f"[{name}] {f['kind']:17} rows {f['rows']:3}  rules {f.get('rules')}  ml {f.get('ml')}  first {f.get('first')}")
        for g, fa in res["false_alarms"].items():
            say(f"[{name}] false alarms {g}: {fa}")
    say(f"subtle: {rep['subtle_text']}")
    say(f"forecast: {rep['forecast']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
        say(f"json: {args.json}")
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(session_report_mod.to_markdown(rep), encoding="utf-8")
        say(f"markdown: {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
