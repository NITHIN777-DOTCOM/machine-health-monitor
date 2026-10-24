"""Sensor registry: enabled / ML lists, group rule, robustness against bad config."""
import logging
import re

import pytest

from app.config import ROOT_DIR
from app.registry import Registry


def _set(data, key, **fields):
    next(s for s in data["sensors"] if s["key"] == key).update(fields)


def test_current_config_lists(registry):
    # Phase 7.1: leak and the HC-SR04 are fitted; they are rule-only (not ML features).
    assert [s.key for s in registry.enabled] == ["temp_c", "humidity", "sound_peak", "vib_count", "leak_raw", "distance_cm"]
    assert [s.key for s in registry.ml] == ["temp_c", "humidity", "sound_peak", "vib_count"]
    assert registry.warnings == []


def test_safety_zone_and_leak_limits(registry):
    d = registry.get("distance_cm")
    assert (d.warn, d.critical, d.direction, d.hysteresis) == (20, 10, "below", 3)
    assert d.out_of_range_value == 400 and d.display_name == "Safety zone (distance)"
    leak = registry.get("leak_raw")
    assert (leak.warn, leak.critical, leak.direction, leak.hysteresis) == (50, 200, "above", 20)
    assert not leak.forecast and not d.forecast and d.limits_note and leak.limits_note
    assert all(s.out_of_range_value is None for s in registry.sensors if s.key != "distance_cm")


def test_shipped_model_matches_the_registry(registry):
    """Enabling rule-only sensors must not force a retrain (no NEEDS_RETRAIN)."""
    from app.config import MODELS_DIR
    from app.ml.scorer import Scorer
    scorer = Scorer.load(registry, MODELS_DIR)
    assert scorer.meta["sensors"] == [s.key for s in registry.ml]
    assert scorer.status == "READY", scorer.message


def test_ml_requires_enabled_and_include_in_ml(make_registry):
    def mutate(d):
        _set(d, "leak_raw", enabled=True, include_in_ml=True)        # enabled + ML
        _set(d, "distance_cm", enabled=False, include_in_ml=True)    # ML but disabled
        _set(d, "current_ma", enabled=True, include_in_ml=False)     # enabled, not ML
        _set(d, "bus_v", enabled=True, include_in_ml=False)
        _set(d, "humidity", include_in_ml=False)
    reg = make_registry(mutate)
    enabled = {s.key for s in reg.enabled}
    ml = {s.key for s in reg.ml}
    assert {"leak_raw", "current_ma", "bus_v"} <= enabled and "distance_cm" not in enabled
    assert ml == {s.key for s in reg.sensors if s.enabled and s.include_in_ml}
    assert ml == {"temp_c", "sound_peak", "vib_count", "leak_raw"}


def test_group_enabled_together(make_registry):
    reg = make_registry(lambda d: (_set(d, "current_ma", enabled=True), _set(d, "bus_v", enabled=True)))
    assert reg.get("current_ma").enabled and reg.get("bus_v").enabled
    assert reg.warnings == []


def test_group_mismatch_disables_whole_group(make_registry, caplog):
    with caplog.at_level(logging.WARNING):
        reg = make_registry(lambda d: _set(d, "current_ma", enabled=True))
    assert not reg.get("current_ma").enabled and not reg.get("bus_v").enabled
    assert reg.get("current_ma").enabled_in_config is True
    assert any("ina219" in w and "DISABLED" in w for w in reg.warnings)
    assert "ina219" in caplog.text


@pytest.mark.parametrize("content", [None, "{not json", "[1, 2, 3]", ""])
def test_missing_or_broken_file_does_not_crash(tmp_path, content):
    path = tmp_path / "sensors.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    reg = Registry.load(path)
    assert reg.sensors == []
    assert reg.warnings and "Could not load sensor registry" in reg.warnings[0]


def test_bad_entries_are_fixed_or_skipped_with_warnings(make_registry):
    def mutate(d):
        _set(d, "temp_c", direction="sideways", hysteresis=-1)
        _set(d, "humidity", warn="high", tier="vital")
        d["sensors"].append({"display_name": "no key"})
        d["sensors"].append({"key": "temp_c"})       # duplicate
        d["sensors"].append({"key": "ms"})           # reserved
    reg = make_registry(mutate)
    t, h = reg.get("temp_c"), reg.get("humidity")
    assert t.direction == "above" and t.hysteresis is None
    assert h.warn is None and h.tier == "optional"
    assert len(reg.sensors) == 8
    assert len(reg.warnings) == 7


def test_missing_csv_columns_falls_back(make_registry):
    reg = make_registry(lambda d: d.pop("csv_columns"))
    assert reg.csv_columns[0] == "ms" and reg.csv_columns[-1] == "dev_state"
    assert any("csv_columns" in w for w in reg.warnings)


def test_limits_and_api_dict(registry):
    assert registry.limits("temp_c") == (32.0, 35.0, "above")
    assert registry.limits("nope") == (None, None, "above")
    d = registry.to_dict()
    temp = next(s for s in d["sensors"] if s["key"] == "temp_c")
    assert temp["hysteresis"] == 0.5 and temp["in_ml"] is True and temp["limits_note"]


def test_registry_columns_match_data_contract_header(registry):
    """The header line documented in DATA_CONTRACT.md must equal csv_columns."""
    doc = (ROOT_DIR / "docs" / "DATA_CONTRACT.md").read_text(encoding="utf-8")
    header = re.search(r"^# (ms,[a-z_,]+)$", doc, re.MULTILINE).group(1)
    assert header.split(",") == registry.csv_columns


def test_ml_stats_parsing(make_registry):
    def edit(d):
        d["sensors"][0]["ml_stats"] = ["slope", "std"]          # any order -> canonical order
        d["sensors"][1]["ml_stats"] = ["median"]               # invalid -> all, with a warning
    reg = make_registry(edit)
    s0, s1 = reg.sensors[0], reg.sensors[1]
    assert s0.ml_stats == ("std", "slope") and s1.ml_stats is None
    assert any("ml_stats" in w for w in reg.warnings)
    assert s0.to_dict()["ml_stats"] == ["std", "slope"]
