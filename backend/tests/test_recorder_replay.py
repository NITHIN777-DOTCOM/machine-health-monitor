"""Recorder -> CSV -> ReplaySource round trip, replay timing, live labels, recordings list."""
import asyncio
import csv
from datetime import datetime, timedelta

import pytest

from app.models import ParseStats, csv_header
from app.recorder import Recorder, list_recordings
from app.sources.replay import ReplaySource, _seconds, resolve_recording
from helpers import collect
from test_serial import HEADER, FakeSerial, line, make_source


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


@pytest.fixture
def recorder(registry, tmp_path):
    return Recorder(registry, tmp_path)


def replay(registry, path, speed=1.0, loop=False, n=None):
    """Replay a file without real sleeping; returns (rows, requested sleep durations)."""
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    src = ReplaySource(registry=registry, stats=ParseStats(), path=path, speed=speed, loop=loop)
    src._sleep = fake_sleep

    async def run():
        if n is not None:
            return await collect(src, n)
        return [r async for r in src.rows()]

    return asyncio.run(run()), sleeps, src


def test_record_writes_header_and_flushes_every_row(registry, recorder, run_sim):
    rows, _ = run_sim("sudden_fault", 60)
    path = recorder.start()
    assert path.name.startswith("session_") and path.suffix == ".csv"
    assert read_csv(path) == [csv_header(registry)]
    for i, r in enumerate(rows[:5], 1):
        recorder.write(r)
        assert len(read_csv(path)) == 1 + i     # on disk while the file is still open
    for r in rows[5:]:
        recorder.write(r)
    summary = recorder.stop()
    assert summary["on"] is False and summary["rows"] == 60 and summary["file"] == path.name
    assert len(read_csv(path)) == 61


def test_replay_reads_back_identically(registry, recorder, run_sim):
    rows, _ = run_sim("sensor_fault", 90)
    path = recorder.start()
    for r in rows:
        recorder.write(r)
    recorder.stop()
    back, _, src = replay(registry, path, speed=10)
    assert len(back) == len(rows) and src.finished
    for a, b in zip(rows, back):
        assert (b.ms, b.values, b.dev_state, b.source, b.label) == (a.ms, a.values, a.dev_state, a.source, a.label)
        assert b.mode == "recorded" and b.ts_iso != ""     # ts_iso is re-stamped at replay time


@pytest.mark.parametrize("speed, gap", [(1, 1.0), (10, 0.1)])
def test_replay_timing_follows_device_ms(registry, recorder, run_sim, speed, gap):
    rows, _ = run_sim("normal", 30)
    path = recorder.start()
    for r in rows:
        recorder.write(r)          # written instantly: ts_iso gaps are ~0, ms gaps are 1000
    recorder.stop()
    _, sleeps, _ = replay(registry, path, speed=speed)
    assert sleeps == pytest.approx([gap] * 29)


def test_gap_falls_back_to_ts_iso_when_ms_jumps():
    t0 = datetime(2026, 10, 23, 12, 0, 0).astimezone()
    a = {"ms": "50000", "ts_iso": t0.isoformat()}
    b = {"ms": "1000", "ts_iso": (t0 + timedelta(seconds=2)).isoformat()}    # device reset
    assert _seconds(b, a) == 2.0
    assert _seconds({"ms": "x"}, {"ms": "y"}) == 1.0
    assert _seconds(a, None) == 0.0


def test_replay_loop(registry, recorder, run_sim):
    rows, _ = run_sim("normal", 5)
    path = recorder.start()
    for r in rows:
        recorder.write(r)
    recorder.stop()
    back, _, src = replay(registry, path, speed=10, loop=True, n=12)
    assert [r.ms for r in back] == [0, 1000, 2000, 3000, 4000] * 2 + [0, 1000]
    assert src.passes == 2


def test_replay_skips_bad_rows(registry, tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(",".join(csv_header(registry)) + "\n"
                    "2026-10-23T12:00:00+05:30,1000,29,60,5,1,,,,,NORMAL,live,real,normal\n"
                    "2026-10-23T12:00:01+05:30,2000,abc,60,5,1,,,,,NORMAL,live,real,normal\n"
                    "2026-10-23T12:00:02+05:30,3000,29,60,5,1,,,,,NORMAL,live,real,fault\n", encoding="utf-8")
    back, _, src = replay(registry, path)
    assert [r.ms for r in back] == [1000, 3000] and src.stats.rejected == 1
    assert [(r.source, r.label) for r in back] == [("real", "normal"), ("real", "fault")]


def test_label_changes_mid_recording_are_saved(registry, recorder):
    """Live serial rows take the recorder's current label (set via POST /api/label)."""
    src = make_source(registry, [FakeSerial([HEADER] + [line(ms) for ms in range(1000, 7000, 1000)])],
                      label_getter=lambda: recorder.label or "unknown")
    path = recorder.start()

    async def run():
        agen = src.rows()
        n = 0
        async for row in agen:
            recorder.write(row)
            n += 1
            if n == 2:
                recorder.set_label("fault")     # inducing a fault on the machine now
            if n == 4:
                recorder.set_label(None)
            if n == 6:
                break
        await agen.aclose()

    asyncio.run(run())
    recorder.stop()
    data = read_csv(path)
    labels = [row[data[0].index("label")] for row in data[1:]]
    assert labels == ["unknown", "unknown", "fault", "fault", "unknown", "unknown"]


def test_set_label_validates(recorder):
    with pytest.raises(ValueError):
        recorder.set_label("broken")


def test_two_recordings_in_the_same_second_get_unique_names(recorder):
    a = recorder.start()
    recorder.stop()
    b = recorder.start()
    recorder.stop()
    assert a != b and a.exists() and b.exists()


def test_list_recordings(registry, recorder, run_sim, tmp_path):
    rows, _ = run_sim("normal", 10)
    path = recorder.start()
    for r in rows:
        recorder.write(r)
    recorder.stop()
    info = list_recordings(tmp_path)
    assert len(info) == 1
    assert info[0]["file"] == path.name and info[0]["rows"] == 10 and info[0]["size_bytes"] > 0
    assert info[0]["duration_s"] is not None and info[0]["error"] is None


@pytest.mark.parametrize("name", ["../secrets.csv", "missing.csv", "notes.txt"])
def test_resolve_recording_rejects_bad_names(tmp_path, name):
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(FileNotFoundError):
        resolve_recording(tmp_path, name)
