"""Data roles (MANIFEST.json) are enforced by train.py, generate_synthetic --from-real, the
API train job and evaluate.py; the validation holdout split never overlaps training."""
import json
import shutil

import pytest

import evaluate as evaluate_cli
import generate_synthetic
import train as train_cli
from app.ml import dataset, roles
from app.ml.dataset import Dataset, Segment
from app.paths import MANIFEST_FILE, REPO_DIR
from helpers import rows_from

REC = REPO_DIR / "data" / "recordings"
TRAIN_FILE = REC / "real_session_01_20261024.csv"
TEST_FILE = REC / "real_session_02_test_20261024.csv"
RAW_TEST = REC / "raw" / "raw_session_20261024_153633.csv"
CORE = {"temp_c": 29.0, "humidity": 60.0, "sound_peak": 5.0, "vib_count": 1.0}


@pytest.fixture(scope="module")
def manifest():
    return roles.Manifest.load(MANIFEST_FILE)


def write(path, registry, rows):
    from test_ml_evaluation import write_csv
    return write_csv(path, registry, rows)


# ---- lookups ------------------------------------------------------------------------

def test_roles_of_the_real_sessions_and_their_raw_variants(manifest):
    assert manifest.role(TRAIN_FILE) == "train"
    assert manifest.role(TEST_FILE) == "test"
    assert manifest.lookup(RAW_TEST).session == TEST_FILE.name and manifest.lookup(RAW_TEST).variant == "raw"
    parts = sorted((REC / "raw").glob("session_20261024_1*.csv"))
    assert len(parts) == 6 and {manifest.role(p) for p in parts} == {"train"}


def test_a_renamed_copy_keeps_its_role(manifest, tmp_path):
    copy = tmp_path / "harmless_name.csv"
    shutil.copy(TEST_FILE, copy)
    assert manifest.role(copy) == "test"


def test_hash_ignores_line_endings(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_bytes(b"x,y\n1,2\n")
    b.write_bytes(b"x,y\r\n1,2\r\n")
    assert roles.content_hash(a) == roles.content_hash(b)


def test_missing_manifest_means_no_roles(tmp_path):
    m = roles.Manifest.load(tmp_path / "none.json")
    assert m.role(TEST_FILE) is None and m.entries == []


# ---- training -----------------------------------------------------------------------

def test_check_training_rules(manifest, tmp_path):
    unlisted = tmp_path / "my_machine.csv"
    unlisted.write_text("x\n", encoding="utf-8")
    with pytest.raises(roles.RoleError, match="role 'test'"):
        roles.check_training([TEST_FILE], {TEST_FILE.name: True}, manifest)
    with pytest.raises(roles.RoleError, match="role 'test'"):               # even in the lenient API mode
        roles.check_training([RAW_TEST], {RAW_TEST.name: True}, manifest, strict=False)
    with pytest.raises(roles.RoleError, match="not listed"):
        roles.check_training([unlisted], {unlisted.name: True}, manifest)
    assert "machine's own" in roles.check_training([unlisted], {unlisted.name: True}, manifest, strict=False)[0]
    assert roles.check_training([unlisted], {unlisted.name: False}, manifest) == []   # synthetic only
    assert "role 'train'" in roles.check_training([TRAIN_FILE], {TRAIN_FILE.name: True}, manifest)[0]


@pytest.mark.parametrize("path", [TEST_FILE, RAW_TEST])
def test_train_cli_refuses_the_test_session(path, tmp_path, capsys):
    assert train_cli.main([str(path), "--out", str(tmp_path / "m")]) == 2
    assert "role 'test'" in capsys.readouterr().err
    assert not (tmp_path / "m").exists()


def test_train_cli_refuses_a_renamed_test_copy(tmp_path, capsys):
    copy = tmp_path / "normal_data.csv"
    shutil.copy(TEST_FILE, copy)
    assert train_cli.main([str(copy), "--out", str(tmp_path / "m")]) == 2
    assert "same content as real_session_02_test" in capsys.readouterr().err


def test_train_cli_refuses_unlisted_real_data(tmp_path, registry, capsys):
    f = write(tmp_path / "real.csv", registry, rows_from([dict(CORE)] * 80, source="real"))
    assert train_cli.main([str(f), "--out", str(tmp_path / "m")]) == 2
    assert "not listed in MANIFEST.json" in capsys.readouterr().err


def test_train_cli_on_the_train_session_with_holdout(tmp_path):
    out = tmp_path / "m"
    assert train_cli.main([str(TRAIN_FILE), "--out", str(out), "--n-estimators", "10", "--holdout-last", "0.2"]) == 0
    meta = json.loads((out / "model_meta.json").read_text(encoding="utf-8"))
    assert meta["trained_on"]["sessions"] == [TRAIN_FILE.name]
    assert meta["provisional"] is False and meta["trained_on"]["synthetic_rows"] == 0
    h = meta["holdout"]
    assert h["train_normal_rows"] + h["holdout_normal_rows"] == 868
    assert meta["trained_on"]["real_rows"] == h["train_normal_rows"]
    assert meta["training"]["rows_skipped_not_normal"]["holdout"] == h["holdout_normal_rows"]


def test_from_real_cli_refuses_the_test_session(tmp_path):
    with pytest.raises(SystemExit, match="role 'test'"):
        generate_synthetic.main(["--from-real", str(TEST_FILE), "--out", str(tmp_path), "--minutes", "1",
                                 "--sessions", "1", "--fault-seeds", "0"])


def test_api_train_job_refuses_the_test_session(registry, tmp_path):
    import asyncio

    from app.config import Settings
    from app.ml.jobs import TrainJobs

    rec = tmp_path / "recordings"
    rec.mkdir()
    shutil.copy(TEST_FILE, rec / TEST_FILE.name)
    shutil.copy(MANIFEST_FILE, rec / "MANIFEST.json")
    settings = Settings(recordings_dir=rec, models_dir=tmp_path / "models")

    async def go():
        async def done():
            raise AssertionError("must not reload a model")
        jobs = TrainJobs(registry, settings, on_done=done)
        job = jobs.start([TEST_FILE.name])
        await jobs._task
        return jobs.view(job["id"])

    view = asyncio.run(go())
    assert view["status"] == "failed" and "role 'test'" in view["message"]
    assert not (tmp_path / "models").exists()


# ---- evaluation ---------------------------------------------------------------------

def test_evaluate_cli_refuses_train_sessions_for_final_numbers(tmp_path, capsys):
    copy = tmp_path / "eval_me.csv"
    shutil.copy(TRAIN_FILE, copy)
    for f in (TRAIN_FILE, copy):
        assert evaluate_cli.main([str(f), "--no-report", "--model-dir", str(tmp_path)]) == 2
        assert "cannot give final test numbers" in capsys.readouterr().err


def test_evaluate_cli_validation_accepts_only_train_sessions(tmp_path, capsys):
    assert evaluate_cli.main([str(TEST_FILE), "--validation", "--no-report", "--model-dir", str(tmp_path)]) == 2
    assert "validation uses 'train' sessions only" in capsys.readouterr().err
    assert evaluate_cli.main([str(TRAIN_FILE), "--validation", "--holdout-last", "0.2", "--no-report",
                              "--model-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "VALIDATION on a training session" in out and "[VALIDATION]" in out


def test_holdout_needs_validation(tmp_path):
    with pytest.raises(SystemExit):
        evaluate_cli.main([str(TEST_FILE), "--holdout-last", "0.2", "--no-report"])


# ---- holdout split ------------------------------------------------------------------

def test_holdout_split_takes_the_last_normal_rows_and_never_overlaps():
    rows = rows_from([dict(CORE)] * 30, source="real")
    for i, r in enumerate(rows):
        r.ts_iso = f"2026-10-24T10:00:{i:02d}"
        r.label = "fault" if 10 <= i < 15 else "normal"
    data = Dataset(["d.csv"], [Segment("d.csv", rows)])
    train, val, info = dataset.holdout_last_normal(data, 0.2)
    assert (info["train_normal_rows"], info["holdout_normal_rows"]) == (20, 5)
    assert info["holdout_from"] == "2026-10-24T10:00:25"
    t_labels = [r.label for r in train.rows]
    v_labels = [r.label for r in val.rows]
    assert t_labels[25:] == ["holdout"] * 5 and t_labels.count("normal") == 20
    assert v_labels[25:] == ["normal"] * 5 and v_labels.count("normal") == 5
    assert v_labels[10:15] == ["fault"] * 5 and t_labels[10:15] == ["fault"] * 5
    assert [r.label for r in data.rows].count("normal") == 25          # the input is not changed
    with pytest.raises(ValueError):
        dataset.holdout_last_normal(data, 1.0)
