"""data/recordings/MANIFEST.json must list every real recording with the right role and counts."""
import csv
import json
from collections import Counter

from app.ml.roles import content_hash
from app.paths import REPO_DIR

REC_DIR = REPO_DIR / "data" / "recordings"
MANIFEST = json.loads((REC_DIR / "MANIFEST.json").read_text(encoding="utf-8"))


def entries():
    """Every listed file: each session's cleaned file and its raw variants."""
    for s in MANIFEST["sessions"]:
        yield s
        yield from s.get("raw", [])


def test_every_recording_is_listed_once():
    listed = [e["file"] for e in entries()]
    assert len(listed) == len(set(listed))
    on_disk = [p.name for p in REC_DIR.glob("*.csv")] + [f"raw/{p.name}" for p in (REC_DIR / "raw").glob("*.csv")]
    assert sorted(listed) == sorted(on_disk)


def test_hashes_match_the_files():
    for e in entries():
        assert e["sha256"] == content_hash(REC_DIR / e["file"]), e["file"]


def test_raw_variants_hold_the_same_rows_as_the_cleaned_file():
    """Same sensor rows, only the labels differ (the clean-up changes labels, nothing else)."""
    for s in MANIFEST["sessions"]:
        if not s.get("raw"):
            continue
        cleaned = [r for r in csv.DictReader(open(REC_DIR / s["file"], encoding="utf-8", newline=""))]
        raw = [r for e in s["raw"] for r in csv.DictReader(open(REC_DIR / e["file"], encoding="utf-8", newline=""))]
        strip = lambda rows: sorted(tuple(v for k, v in r.items() if k != "label") for r in rows)  # noqa: E731
        assert strip(cleaned) == strip(raw), s["file"]


def test_session_02_steps_file_exists():
    s2 = next(s for s in MANIFEST["sessions"] if s["role"] == "test")
    assert (REC_DIR / s2["steps_file"]).is_file() and (REC_DIR / s2["cleanup_script"]).is_file()


def test_roles_are_train_or_test_and_both_exist():
    roles = {s["file"]: s["role"] for s in MANIFEST["sessions"]}
    assert set(roles.values()) == {"train", "test"}
    assert roles["real_session_01_20261024.csv"] == "train"
    assert roles["real_session_02_test_20261024.csv"] == "test"


def test_counts_match_the_files():
    for s in entries():
        with open(REC_DIR / s["file"], encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        labels = Counter(r["label"] for r in rows)
        assert s["rows"] == len(rows), s["file"]
        assert s["labels"] == {k: labels.get(k, 0) for k in ("normal", "fault", "unknown")}, s["file"]
        assert {r["source"] for r in rows} == {"real"} and {r["mode"] for r in rows} == {"live"}, s["file"]
