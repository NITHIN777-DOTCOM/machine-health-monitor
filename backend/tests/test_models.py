"""parse_line and CSV helpers (DATA_CONTRACT.md sections 2-5)."""
import csv
import io
import logging

import pytest

from app.models import (ParseStats, SensorRow, csv_header, parse_line, row_from_stored,
                        stored_columns)

HEADER = "# ms,temp_c,humidity,sound_peak,vib_count,leak_raw,distance_cm,current_ma,bus_v,dev_state"
FULL = "12000,29.0,62.0,4,0,18,41.3,182.4,4.98,NORMAL"


@pytest.fixture
def stats():
    return ParseStats()


def test_valid_line(registry, stats):
    row = parse_line(FULL, registry, stats)
    assert row is not None
    assert row.ms == 12000
    assert row.values == {"temp_c": 29.0, "humidity": 62.0, "sound_peak": 4.0, "vib_count": 0.0,
                          "leak_raw": 18.0, "distance_cm": 41.3, "current_ma": 182.4, "bus_v": 4.98}
    assert row.dev_state == "NORMAL"
    assert (row.mode, row.source, row.label) == ("live", "real", "unknown")
    assert (stats.accepted, stats.rejected) == (1, 0)


def test_header_line_is_recognised_and_ignored(registry, stats, caplog):
    with caplog.at_level(logging.INFO):
        assert parse_line(HEADER, registry, stats) is None
    assert stats.comments == 1 and stats.rejected == 0
    assert "matches the registry" in caplog.text


def test_mismatched_header_is_reported(registry, stats, caplog):
    assert parse_line("# ms,temp_c,dev_state", registry, stats) is None
    assert "does not match" in caplog.text
    assert stats.rejected == 0


def test_comment_line_is_ignored(registry, stats):
    assert parse_line("# DHT11 init OK", registry, stats) is None
    assert stats.comments == 1 and stats.rejected == 0 and stats.accepted == 0


def test_empty_fields_are_none_not_zero(registry, stats):
    row = parse_line("14000,,,5,0,,,,,WARNING", registry, stats)
    assert row is not None
    assert row.values["temp_c"] is None and row.values["humidity"] is None
    assert row.values["vib_count"] == 0.0  # a real zero stays zero
    assert all(row.values[k] is None for k in ("leak_raw", "distance_cm", "current_ma", "bus_v"))


@pytest.mark.parametrize("line, reason", [
    ("15000,29,62,4,0", "expected 10 fields"),
    ("15000,29,62,4,0,,,,,,,NORMAL", "expected 10 fields"),
    ("16000,abc,62,4,0,,,,,NORMAL", "could not convert"),
    ("16000,nan,62,4,0,,,,,NORMAL", "non-finite"),
    ("17000,29,62,4,0,,,,,BROKEN", "bad dev_state"),
    ("17000,29,62,4,0,,,,,", "bad dev_state"),
    (",29,62,4,0,,,,,NORMAL", "bad ms"),
    ("1.5,29,62,4,0,,,,,NORMAL", "bad ms"),
])
def test_malformed_lines_are_rejected_and_counted(registry, stats, line, reason):
    assert parse_line(line, registry, stats) is None
    assert stats.rejected == 1
    assert reason in stats.last_reject_reason


def test_trailing_crlf_is_tolerated(registry, stats):
    row = parse_line(FULL + "\r\n", registry, stats)
    assert row is not None and row.dev_state == "NORMAL" and row.values["bus_v"] == 4.98


@pytest.mark.parametrize("line", ["", "\n", "\r\n", "   "])
def test_blank_line_is_ignored_silently(registry, stats, line):
    assert parse_line(line, registry, stats) is None
    assert (stats.accepted, stats.rejected, stats.comments) == (0, 0, 0)


def test_parse_never_raises_on_junk(registry, stats):
    for junk in ["\x00\xff", ",,,,,,,,,", "#", "a" * 5000, "1,2,3,4,5,6,7,8,9,NORMAL,extra"]:
        parse_line(junk, registry, stats)  # must not raise


def test_meta_columns_can_be_set(registry):
    row = parse_line(FULL, registry, mode="recorded", source="synthetic", label="fault")
    assert (row.mode, row.source, row.label) == ("recorded", "synthetic", "fault")


def test_stored_column_order(registry):
    assert stored_columns(registry) == [
        "ts_iso", "ms", "temp_c", "humidity", "sound_peak", "vib_count", "leak_raw",
        "distance_cm", "current_ma", "bus_v", "dev_state", "mode", "source", "label",
    ]
    assert csv_header(registry) == stored_columns(registry)


def _roundtrip(rows, registry):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(csv_header(registry))
    for r in rows:
        w.writerow(r.to_csv_row(registry))
    buf.seek(0)
    return [row_from_stored(rec, registry) for rec in csv.DictReader(buf)]


def test_csv_roundtrip_is_identical(registry, run_sim):
    rows, _ = run_sim("sensor_fault", 90)  # includes empty fields and two labels
    rows.append(SensorRow(ms=5, values={k: None for k in registry.sensor_keys}, dev_state="WARNING",
                          mode="live", source="real", label="unknown"))
    back = _roundtrip(rows, registry)
    assert back == rows


def test_device_line_roundtrip(registry, run_sim):
    rows, _ = run_sim("sudden_fault", 80)
    for r in rows:
        parsed = parse_line(r.to_device_line(registry), registry)
        assert parsed is not None
        assert (parsed.ms, parsed.values, parsed.dev_state) == (r.ms, r.values, r.dev_state)


def test_row_from_stored_rejects_bad_state(registry):
    with pytest.raises(ValueError):
        row_from_stored({"ms": "1000", "dev_state": "BAD"}, registry)
