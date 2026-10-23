"""Simulator scenarios: contract-valid rows, physical ranges, and the expected state stories."""
import asyncio

import pytest

from app.device_rules import DeviceStateMachine
from app.models import LABELS, ParseStats, parse_line
from app.sources.simulator import SimulatorSource, load_profile
from helpers import collapse, collect, reversals_within, transitions

SCENARIOS = sorted(load_profile()["scenarios"])
SEEDS = range(5)
SECONDS = 420  # long enough for every scenario, including drift_and_recover's full cycle


def states(rows):
    return [r.dev_state for r in rows]


def first_index(rows, pred):
    return next((i for i, r in enumerate(rows) if pred(r)), None)


def test_all_expected_scenarios_exist():
    assert {"normal", "sudden_fault", "slow_drift", "sensor_fault", "recovery", "drift_and_recover"} <= set(SCENARIOS)


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("seed", SEEDS)
def test_rows_are_contract_valid(registry, profile, run_sim, scenario, seed):
    rows, _ = run_sim(scenario, SECONDS, seed)
    for i, r in enumerate(rows):
        assert r.ms == i * 1000
        assert (r.mode, r.source) == ("simulated", "synthetic") and r.label in LABELS
        parsed = parse_line(r.to_device_line(registry), registry)       # what the backend would accept
        assert parsed is not None and parsed.values == r.values and parsed.dev_state == r.dev_state
        for s in registry.sensors:
            v = r.values[s.key]
            if not s.enabled:
                assert v is None, f"disabled {s.key} must be empty"
            elif v is not None:
                cfg = profile["sensors"][s.key]
                assert cfg["physical_min"] <= v <= cfg["physical_max"], (s.key, v)


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("seed", SEEDS)
def test_no_reversals_within_hold_seconds(run_sim, scenario, seed):
    rows, _ = run_sim(scenario, SECONDS, seed)
    assert reversals_within(states(rows), 5) == []


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_pipeline_mirror_agrees_with_simulator(registry, run_sim, scenario):
    rows, _ = run_sim(scenario, SECONDS, seed=3)
    mirror = DeviceStateMachine(registry, 5)
    assert [mirror.update(r.values) for r in rows] == states(rows)


def test_enabled_optional_sensors_get_values(make_registry, run_sim):
    reg = make_registry(lambda d: [s.update(enabled=True) for s in d["sensors"]])
    rows, _ = run_sim("normal", 30, reg=reg)
    assert all(v is not None for r in rows for v in r.values.values())


def test_normal_stays_normal(run_sim):
    for seed in SEEDS:
        rows, _ = run_sim("normal", SECONDS, seed)
        assert set(states(rows)) == {"NORMAL"} and {r.label for r in rows} == {"normal"}


@pytest.mark.parametrize("seed", SEEDS)
def test_sudden_fault_reaches_critical(run_sim, seed):
    rows, _ = run_sim("sudden_fault", 120, seed)
    start = first_index(rows, lambda r: r.label == "fault")
    assert 20 <= start <= 61
    assert "CRITICAL" in states(rows)[start:]
    assert set(states(rows)[:start]) == {"NORMAL"}


@pytest.mark.parametrize("seed", SEEDS)
def test_slow_drift_crosses_32_then_35_and_stays_below_50(run_sim, seed):
    rows, _ = run_sim("slow_drift", 300, seed)
    temps = [r.values["temp_c"] for r in rows]
    i32 = first_index(rows, lambda r: r.values["temp_c"] >= 32)
    i35 = first_index(rows, lambda r: r.values["temp_c"] >= 35)
    assert i32 is not None and i35 is not None and i32 < i35
    assert max(temps) < 50
    # Temperature drives CRITICAL: it appears exactly when temp first reaches 35, never before,
    # and the device is at least WARNING from the moment temp reaches 32. (Vibration also
    # rises in this scenario and may cause a short, held WARNING earlier.)
    st = states(rows)
    assert st.index("CRITICAL") == i35
    assert all(s != "NORMAL" for s in st[i32:])


@pytest.mark.parametrize("seed", SEEDS)
def test_sensor_fault_empties_dht_and_is_labelled_unknown(run_sim, seed):
    rows, _ = run_sim("sensor_fault", 120, seed)
    start = first_index(rows, lambda r: r.values["temp_c"] is None)
    assert start is not None
    for r in rows[start:]:
        assert r.values["temp_c"] is None and r.values["humidity"] is None
        assert r.label == "unknown" and r.dev_state != "NORMAL"
    assert {r.label for r in rows[:start]} == {"normal"}


@pytest.mark.parametrize("seed", SEEDS)
def test_recovery_returns_to_normal_with_countdown(run_sim, seed):
    rows, snaps = run_sim("recovery", 90, seed)
    assert collapse(states(rows)) == ["NORMAL", "CRITICAL", "WARNING", "NORMAL"]
    assert collapse([r.label for r in rows]) == ["normal", "fault", "normal"]
    # Label goes back to normal when the values return; the state follows after the holds.
    back = first_index(rows[25:], lambda r: r.label == "normal") + 25
    tr = transitions(states(rows))
    assert tr[-1][0] - back == 9, "CRITICAL->WARNING after 4 more rows, WARNING->NORMAL after 5 more"
    countdown = [s["hold_remaining_s"] for s in snaps[back:tr[-1][0] + 1]]
    assert countdown == [4, 3, 2, 1, 5, 4, 3, 2, 1, None]


@pytest.mark.parametrize("seed", SEEDS)
def test_drift_and_recover_cycle(run_sim, profile, seed):
    rows, _ = run_sim("drift_and_recover", SECONDS, seed)
    assert collapse(states(rows)) == ["NORMAL", "WARNING", "CRITICAL", "WARNING", "NORMAL"]
    assert collapse([r.label for r in rows]) == ["normal", "fault", "normal"]
    temps = [r.values["temp_c"] for r in rows]
    assert max(temps) < 50 and temps[-1] < 32


def test_unknown_scenario_is_rejected(registry):
    with pytest.raises(ValueError, match="unknown scenario"):
        SimulatorSource(registry=registry, stats=ParseStats(), scenario="nope")


def test_async_rows_at_high_speed(registry, profile):
    events = []

    async def on_change():
        events.append("change")

    sim = SimulatorSource(registry=registry, stats=ParseStats(), scenario="normal", speed=1000,
                          profile=profile, on_change=on_change)
    rows = asyncio.run(collect(sim, 20, timeout=1))
    assert [r.ms for r in rows] == [i * 1000 for i in range(20)]
    assert sim.connected and events == ["change"]
    assert sim.status()["scenario"] == "normal"
