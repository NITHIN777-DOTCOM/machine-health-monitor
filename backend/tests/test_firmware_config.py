"""firmware/machine_monitor/config_generated.h must match sensors.json + settings.json."""
import re

import gen_firmware_config as gen
from app.device_rules import DeviceStateMachine
from app.registry import Registry


def test_generated_header_is_up_to_date():
    current = gen.HEADER_PATH.read_text(encoding="utf-8")
    assert current == gen.render(*gen.load_inputs()), (
        "config_generated.h is out of date: run backend\\venv\\Scripts\\python backend\\scripts\\gen_firmware_config.py")
    assert current.startswith("// GENERATED - do not edit, run gen_firmware_config.py")


def test_header_carries_registry_limits_and_flags(registry):
    text = gen.render(*gen.load_inputs())
    assert "#define HOLD_SECONDS 5" in text
    assert re.search(r"#define USE_HCSR04\s+1", text) and re.search(r"#define USE_LEAK\s+1", text)
    assert re.search(r"#define USE_INA219\s+0", text) and re.search(r"#define USE_DHT11\s+1", text)
    assert "{20.0f, 10.0f, 3.0f, RULE_HAS_WARN | RULE_HAS_CRIT | RULE_BELOW | RULE_ENABLED},  // distance_cm" in text
    assert "{32.0f, 35.0f, 0.5f, RULE_HAS_WARN | RULE_HAS_CRIT | RULE_CORE | RULE_ENABLED},  // temp_c" in text
    assert "{0.0f, 0.0f, 0.0f, 0},  // current_ma" in text            # disabled, no limits
    assert f'#define CSV_HEADER "# {",".join(registry.csv_columns)}"' in text
    assert "#define DISTANCE_CM_OUT_OF_RANGE 400.0f" in text


def test_a_limit_change_changes_the_header():
    sensors, settings, doc = gen.load_inputs()
    before = gen.render(sensors, settings, doc)
    next(s for s in sensors["sensors"] if s["key"] == "vib_count")["warn"] = 25
    assert gen.render(sensors, settings, doc) != before
    assert gen.render(sensors, {**settings, "hold_seconds": 7}, doc) != before


def test_parity_cases_cover_both_directions_and_all_states():
    sensors, settings, doc = gen.load_inputs()
    cases = gen.parity_cases(sensors, settings["hold_seconds"], doc)
    assert [c[0] for c in cases] == ["example1", "example2", "full"]
    for name, reg, hold, rows in cases:
        sm = DeviceStateMachine(reg, hold)
        states = {sm.update(r) for r in rows}
        assert states == {"NORMAL", "WARNING", "CRITICAL"}, name
    assert {s.direction for s in cases[2][1].enabled} == {"above", "below"}
    assert len(cases[2][3]) < 256                       # firmware stores the row count in a uint8_t
    assert isinstance(cases[2][1], Registry)
