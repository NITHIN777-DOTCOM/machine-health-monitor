"""data/recordings/MANIFEST.json must list every real recording with the right role and counts."""
import csv
import json
from collections import Counter

from app.paths import REPO_DIR

REC_DIR = REPO_DIR / "data" / "recordings"
MANIFEST = json.loads((REC_DIR / "MANIFEST.json").read_text(encoding="utf-8"))


def test_every_recording_is_listed_once():
    listed = [s["file"] for s in MANIFEST["sessions"]]
    assert len(listed) == len(set(listed))
    assert sorted(listed) == sorted(p.name for p in REC_DIR.glob("*.csv"))


def test_roles_are_train_or_test_and_both_exist():
    roles = {s["file"]: s["role"] for s in MANIFEST["sessions"]}
    assert set(roles.values()) == {"train", "test"}
    assert roles["real_session_01_20261024.csv"] == "train"
    assert roles["real_session_02_test_20261024.csv"] == "test"


def test_counts_match_the_files():
    for s in MANIFEST["sessions"]:
        with open(REC_DIR / s["file"], encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        labels = Counter(r["label"] for r in rows)
        assert s["rows"] == len(rows), s["file"]
        assert s["labels"] == {k: labels.get(k, 0) for k in ("normal", "fault", "unknown")}, s["file"]
        assert {r["source"] for r in rows} == {"real"} and {r["mode"] for r in rows} == {"live"}, s["file"]
