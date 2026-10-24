"""DeviceStateMachine: escalation, hysteresis, hold time (DATA_CONTRACT.md section 3)."""
import pytest

from app.config import ROOT_DIR
from app.device_rules import DeviceStateMachine, evaluate, triggers
import gen_firmware_config as gen
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


# ---- the worked examples in DATA_CONTRACT.md ------------------------------------------
# Parsed by the same code that writes the firmware parity vectors (gen_firmware_config.py).

def _examples():
    return gen.parse_examples((ROOT_DIR / "docs" / "DATA_CONTRACT.md").read_text(encoding="utf-8"))


def test_data_contract_worked_example():
    ex = _examples()[0]
    assert (ex.key, ex.direction, ex.warn, ex.critical, ex.h, ex.hold) == ("temp_c", "above", 32, 35, 0.5, 5)
    assert [s[0] for s in ex.steps] == list(range(1, 20)), "worked example must have rows 1..19"
    reg = make_reg(sensor("temp_c", ex.warn, ex.critical, hysteresis=ex.h))
    sm = DeviceStateMachine(reg, ex.hold)
    for row, value, expected in ex.steps:
        assert sm.update({"temp_c": value}) == expected, f"worked example row {row}"


def test_data_contract_worked_example_2_safety_zone_below(sensors_data):
    ex = _examples()[1]
    assert (ex.key, ex.direction, ex.warn, ex.critical, ex.h, ex.hold) == ("distance_cm", "below", 20, 10, 3, 5)
    assert [s[0] for s in ex.steps] == list(range(1, 21))
    reg = gen.example_registry(ex, sensors_data)
    assert reg.get("distance_cm").tier == "optional"
    sm = DeviceStateMachine(reg, ex.hold)
    for row, value, expected in ex.steps:
        assert sm.update({"distance_cm": value}) == expected, f"worked example 2 row {row}"


def test_real_registry_safety_zone(registry):
    """distance_cm in the real registry: below 20 warn / 10 crit, 400 (no echo) is clear."""
    sm = DeviceStateMachine(registry, 5)
    base = {"temp_c": 29.0, "humidity": 60.0, "sound_peak": 5.0, "vib_count": 0.0, "leak_raw": 6.0}
    assert sm.update({**base, "distance_cm": 400.0}) == "NORMAL"
    assert sm.update({**base, "distance_cm": 20.0}) == "WARNING"
    assert sm.snapshot()["reason"] == "Safety zone (distance) 20 <= warn 20"
    assert sm.update({**base, "distance_cm": 9.9}) == "CRITICAL"
    assert [sm.update({**base, "distance_cm": 12.9}) for _ in range(6)] == ["CRITICAL"] * 6   # inside 10..13
    assert [sm.update({**base, "distance_cm": 400.0}) for _ in range(5)][-1] == "WARNING"
    assert sm.update({**base, "distance_cm": None}) == "WARNING"     # optional: empty does not raise
    assert [sm.update({**base, "distance_cm": 150.0}) for _ in range(5)][-1] == "NORMAL"
