"""Evaluation data rules, metric definitions, the CLI stamp, and the generator/train scripts."""
import csv
import json

import pytest

import evaluate as evaluate_cli
import generate_synthetic
import train as train_cli
from app.config import Settings
from app.ml import evaluation
from app.ml.dataset import Dataset, Segment, load
from app.models import csv_header
from helpers import rows_from, run_scenario

CORE = {"temp_c": 29.0, "humidity": 60.0, "sound_peak": 5.0, "vib_count": 1.0}


def write_csv(path, registry, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(csv_header(registry))
        for r in rows:
            w.writerow(r.to_csv_row(registry))
    return path


def crafted_rows():
    """40 real rows: normal 0-19, fault 20-29 (CRITICAL from 23), normal 30-39 (one WARNING at 35)."""
    rows = rows_from([dict(CORE) for _ in range(40)], source="real")
    for i, r in enumerate(rows):
        r.label = "fault" if 20 <= i <= 29 else "normal"
        r.dev_state = "CRITICAL" if 23 <= i <= 29 else ("WARNING" if i == 35 else "NORMAL")
    return rows


# ---- data rules ----------------------------------------------------------------------

def test_refuses_synthetic_without_flag():
    rows = rows_from([dict(CORE)] * 20, source="synthetic", label="fault")
    data = Dataset(["s.csv"], [Segment("s.csv", rows)])
    with pytest.raises(evaluation.EvaluationRefused, match="REAL rows labelled 'fault'"):
        evaluation.select(data)
    selected, notes = evaluation.select(data, allow_synthetic=True)
    assert len(selected.rows) == 20 and "development checks only" in notes[0]


def test_refuses_real_data_without_faults():
    data = Dataset(["r.csv"], [Segment("r.csv", rows_from([dict(CORE)] * 20, source="real"))])
    with pytest.raises(evaluation.EvaluationRefused, match="induced faults"):
        evaluation.select(data)


def test_synthetic_rows_are_dropped_from_mixed_input():
    real = crafted_rows()
    synth = rows_from([dict(CORE)] * 15, source="synthetic", label="fault", start_ms=100_000)
    data = Dataset(["m.csv"], [Segment("m.csv", real), Segment("s.csv", synth)])
    selected, notes = evaluation.select(data)
    assert {r.source for r in selected.rows} == {"real"} and "15 synthetic rows ignored" in notes[0]


# ---- metrics -------------------------------------------------------------------------

def test_metric_definitions_on_crafted_data(registry):
    data = Dataset(["c.csv"], [Segment("c.csv", crafted_rows())])
    result = evaluation.run(data, registry, None, Settings())
    assert result["detectors"] == ["rules", "rules_critical", "forecast"]   # no model -> no ml
    rules = result["metrics"]["rules"]
    # windows start at row 9 (10 s window): normal rows 9-19 and 30-39 = 21, fault rows 20-29 = 10
    assert (rules["fault"], rules["fault_flagged"], rules["normal"], rules["normal_flagged"]) == (10, 7, 21, 1)
    assert rules["detection_rate"] == pytest.approx(0.7)
    assert rules["false_alarm_rate"] == pytest.approx(1 / 21)
    assert (rules["episodes"], rules["episodes_detected"], rules["mean_delay_s"]) == (1, 1, 3.0)
    assert result["metrics"]["rules_critical"]["false_alarm_rate"] == 0
    assert result["metrics"]["forecast"]["episodes_detected"] == 0      # flat values: nothing to forecast


def test_unknown_rows_are_not_evaluated(registry):
    rows = crafted_rows()
    for r in rows[30:]:
        r.label = "unknown"
    m = evaluation.run(Dataset(["c"], [Segment("c", rows)]), registry, None, Settings())["metrics"]["rules"]
    assert m["normal"] == 11


def test_report_is_stamped_when_simulated(registry):
    data = Dataset(["c.csv"], [Segment("c.csv", crafted_rows())])
    result = evaluation.run(data, registry, None, Settings())
    lines = evaluation.format_lines(result, simulated=True)
    assert lines and all(l.startswith(f"[{evaluation.STAMP}]") for l in lines)
    report = evaluation.format_report(result, files=["c.csv"], counts=data.counts(), notes=[],
                                      model_info=None, simulated=True)
    assert report.count(evaluation.STAMP) >= 3
    real = evaluation.format_report(result, files=["c.csv"], counts=data.counts(), notes=[],
                                    model_info=None, simulated=False)
    assert evaluation.STAMP not in real


# ---- scripts -------------------------------------------------------------------------

@pytest.fixture
def synthetic_fault_file(tmp_path, registry, profile):
    rows, _ = run_scenario(registry, profile, "recovery", 70, seed=1)
    return write_csv(tmp_path / "devfault_recovery.csv", registry, rows)


def test_cli_refuses_synthetic_without_flag(synthetic_fault_file, tmp_path, capsys):
    code = evaluate_cli.main([str(synthetic_fault_file), "--model-dir", str(tmp_path), "--out-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert code == 2 and "Evaluation refused" in err and "--dev-synthetic" in err
    assert not list(tmp_path.glob("eval_*.md"))


def test_cli_dev_synthetic_stamps_everything(synthetic_fault_file, tmp_path, capsys):
    code = evaluate_cli.main([str(synthetic_fault_file), "--dev-synthetic",
                              "--model-dir", str(tmp_path), "--out-dir", str(tmp_path)])
    out = capsys.readouterr().out.strip().splitlines()
    assert code == 0 and out
    assert all(l.startswith(f"[{evaluation.STAMP}]") for l in out)
    reports = list(tmp_path.glob("eval_*_SIMULATED.md"))
    assert len(reports) == 1 and evaluation.STAMP in reports[0].read_text(encoding="utf-8")


def test_generate_and_train_scripts(tmp_path):
    out = tmp_path / "syn"
    assert generate_synthetic.main(["--minutes", "4", "--sessions", "2", "--fault-seeds", "0",
                                    "--out", str(out)]) == 0
    files = sorted(out.glob("normal_s*.csv"))
    assert len(files) == 2
    data = load([str(f) for f in files], generate_synthetic.Registry.load())
    assert data.counts() == {"source": {"synthetic": 240}, "label": {"normal": 240}}

    models = tmp_path / "models"
    assert train_cli.main([str(out / "normal_s*.csv"), "--out", str(models), "--n-estimators", "20"]) == 0
    meta = json.loads((models / "model_meta.json").read_text(encoding="utf-8"))
    assert meta["provisional"] is True and meta["training"]["rows_normal_by_source"]["synthetic"] == 240
    assert sorted(meta["training"]["files"]) == ["normal_s00.csv", "normal_s01.csv"]


def test_from_real_uses_real_baselines(tmp_path, registry, profile):
    rows, _ = run_scenario(registry, profile, "normal", 120, seed=2)
    for r in rows:
        r.source = "real"
        r.values["temp_c"] = 40.0 + (r.ms // 1000) % 2      # very different from sim_profile (29.5)
    real = write_csv(tmp_path / "real.csv", registry, rows)
    prof = generate_synthetic.profile_from_real(profile, [str(real)], registry)
    assert prof["sensors"]["temp_c"]["mean"] == pytest.approx(40.5)
    assert prof["sensors"]["temp_c"]["min"] >= 40.0


def test_from_real_requires_real_normal_rows(tmp_path, registry, profile):
    rows, _ = run_scenario(registry, profile, "normal", 60, seed=2)      # synthetic rows
    f = write_csv(tmp_path / "syn.csv", registry, rows)
    with pytest.raises(SystemExit):
        generate_synthetic.profile_from_real(profile, [str(f)], registry)
