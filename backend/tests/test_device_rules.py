"""DeviceStateMachine: escalation, hysteresis, hold time (DATA_CONTRACT.md section 3)."""
import re

import pytest

from app.config import ROOT_DIR
from app.device_rules import DeviceStateMachine, evaluate, triggers
from helpers import make_reg, sensor


@pytest.fixture
def temp_reg():
    """One core 'above' sensor: warn 32, critical 35, h 0.5 (same as temp_c)."""
    return make_reg(sensor("t", 32, 35, hysteresis=0.5))


def feed(sm, key, values):
    return [sm.update({key: v}) for v in values]


# ---- escalation ----------------------------------------------------------------------

def test_escalation_to_warning_is_immediate(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    assert feed(sm, "t", [30, 32]) == ["NORMAL", "WARNING"]


def test_escalation_can_skip_warning(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    assert feed(sm, "t", [30, 35]) == ["NORMAL", "CRITICAL"]


def test_warning_to_critical_is_immediate_and_resets_hold(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    feed(sm, "t", [33, 30, 30])           # WARNING, clearing (hold 2)
    assert sm.hold_count == 2
    assert sm.update({"t": 36}) == "CRITICAL"
    assert sm.hold_count == 0


# ---- de-escalation -------------------------------------------------------------------

def test_inside_hysteresis_band_never_clears(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    states = feed(sm, "t", [32] + [31.6] * 30)     # 31.6 is below 32 but inside 31.5..32
    assert set(states) == {"WARNING"}
    assert sm.hold_remaining_s is None


def test_needs_hold_seconds_consecutive_rows(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    states = feed(sm, "t", [32] + [31.0] * 5)
    assert states == ["WARNING"] * 5 + ["NORMAL"]


def test_hold_countdown_is_reported(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    sm.update({"t": 32})
    remaining = []
    for _ in range(5):
        sm.update({"t": 31.0})
        remaining.append(sm.hold_remaining_s)
    assert remaining == [4, 3, 2, 1, None]
    assert sm.state == "NORMAL"


def test_one_level_at_a_time(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    states = feed(sm, "t", [36] + [20.0] * 10)
    assert states[5] == "WARNING"        # first step down after 5 clear rows
    assert states[6:10] == ["WARNING"] * 4
    assert states[10] == "NORMAL"        # second step needs its own 5 rows
    assert "CRITICAL" not in states[6:]


def test_back_inside_margin_resets_hold(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    states = feed(sm, "t", [32, 31, 31, 31, 31.7, 31, 31, 31, 31])
    assert set(states) == {"WARNING"}    # 3 clear, reset, 4 clear: not enough
    assert sm.update({"t": 31}) == "NORMAL"


def test_hold_zero_steps_down_every_row(temp_reg):
    sm = DeviceStateMachine(temp_reg, 0)
    assert feed(sm, "t", [36, 20, 20]) == ["CRITICAL", "WARNING", "NORMAL"]


def test_reset(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    sm.update({"t": 40})
    sm.reset()
    assert sm.snapshot()["state"] == "NORMAL" and sm.snapshot()["reasons"] == []


# ---- direction "below" -----------------------------------------------------------------

def test_direction_below():
    reg = make_reg(sensor("d", warn=10, critical=5, direction="below", hysteresis=1))
    sm = DeviceStateMachine(reg, 3)
    assert feed(sm, "d", [20, 10]) == ["NORMAL", "WARNING"]          # <= warn
    assert feed(sm, "d", [10.8] * 5) == ["WARNING"] * 5              # inside 10..11 band
    assert feed(sm, "d", [11.5] * 3) == ["WARNING", "WARNING", "NORMAL"]
    assert feed(sm, "d", [5]) == ["CRITICAL"]                        # <= critical
    assert feed(sm, "d", [5.9] * 4) == ["CRITICAL"] * 4              # inside 5..6 band
    assert feed(sm, "d", [6.5] * 3)[-1] == "WARNING"                 # clear of critical + h


# ---- faults and disabled sensors -------------------------------------------------------

def test_enabled_core_sensor_empty_is_at_least_warning():
    reg = make_reg(sensor("t", 32, 35), sensor("v", 20, 60, tier="core"))
    sm = DeviceStateMachine(reg, 5)
    assert sm.update({"t": None, "v": 0}) == "WARNING"
    assert sm.snapshot()["reasons"][0]["kind"] == "fault"
    assert sm.snapshot()["reason"] == "SENSOR FAULT: T-HW"
    assert sm.update({"t": None, "v": 70}) == "CRITICAL"            # fault + critical -> CRITICAL


def test_fault_clears_only_after_hold():
    reg = make_reg(sensor("t", 32, 35))
    sm = DeviceStateMachine(reg, 5)
    assert feed(sm, "t", [None, 30, 30, 30, 30, 30]) == ["WARNING"] * 5 + ["NORMAL"]


def test_optional_sensor_empty_has_no_effect():
    reg = make_reg(sensor("t", 32, 35), sensor("leak", 100, 300, tier="optional"))
    sm = DeviceStateMachine(reg, 5)
    assert sm.update({"t": 30, "leak": None}) == "NORMAL"


def test_disabled_sensor_has_no_effect():
    reg = make_reg(sensor("t", 32, 35), sensor("x", 1, 2, tier="core", enabled=False))
    sm = DeviceStateMachine(reg, 5)
    assert sm.update({"t": 30, "x": None}) == "NORMAL"
    assert sm.update({"t": 30, "x": 999}) == "NORMAL"


def test_null_limits_never_trigger():
    reg = make_reg(sensor("h", None, None))
    assert DeviceStateMachine(reg, 5).update({"h": 1e9}) == "NORMAL"


def test_reason_texts(temp_reg):
    sm = DeviceStateMachine(temp_reg, 5)
    sm.update({"t": 35.2})
    assert sm.snapshot()["reason"] == "T 35.2 >= crit 35"
    sm.update({"t": 34.8})
    r = sm.snapshot()["reasons"][0]
    assert r["in_band"] is True and "near crit 35" in r["text"]
    sm.update({"t": 30})                       # clear: counting down, reason is history
    assert sm.snapshot()["reason"] == "recovering, was: T 34.8 near crit 35 (hysteresis)"


def test_stateless_evaluate_matches_triggers(registry):
    values = {"temp_c": 33.0, "humidity": 50.0, "sound_peak": 130.0, "vib_count": 0.0}
    state, reasons = evaluate(values, registry)
    assert state == "CRITICAL" and len(reasons) == 2
    assert {t.sensor for t in triggers(values, registry)} == {"temp_c", "sound_peak"}


# ---- the worked example in DATA_CONTRACT.md -------------------------------------------

def _worked_example():
    """Parse the 'Worked example' table from DATA_CONTRACT.md into (params, [(value, state)])."""
    doc = (ROOT_DIR / "docs" / "DATA_CONTRACT.md").read_text(encoding="utf-8")
    section = doc.split("#### Worked example", 1)[1]
    heading = section.splitlines()[0]
    params = {k: float(v) for k, v in re.findall(r"(warn|critical|h|hold) ([\d.]+)", heading)}
    table = [l for l in section.split("\n\n", 2)[1].splitlines() if l.startswith("|")][2:]
    steps = []
    for line in table:
        rows_cell, value_cell, state_cell = [c.strip() for c in line.strip("|").split("|")][:3]
        lo, _, hi = rows_cell.replace("–", "-").partition("-")
        lo, hi = int(lo), int(hi or lo)
        value = None if value_cell == "empty" else float(value_cell)
        states = re.findall(r"`(NORMAL|WARNING|CRITICAL)`", state_cell)
        at = re.search(r"at row (\d+)", state_cell)
        for row in range(lo, hi + 1):
            expected = states[1] if at and row >= int(at.group(1)) else states[0]
            steps.append((row, value, expected))
    return params, steps


def test_data_contract_worked_example():
    params, steps = _worked_example()
    assert params == {"warn": 32, "critical": 35, "h": 0.5, "hold": 5}
    assert [s[0] for s in steps] == list(range(1, 20)), "worked example must have rows 1..19"
    reg = make_reg(sensor("temp_c", params["warn"], params["critical"], hysteresis=params["h"]))
    sm = DeviceStateMachine(reg, int(params["hold"]))
    for row, value, expected in steps:
        assert sm.update({"temp_c": value}) == expected, f"worked example row {row}"
