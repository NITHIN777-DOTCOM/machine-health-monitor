"""Generate firmware/machine_monitor/config_generated.h from the JSON config.

    python scripts/gen_firmware_config.py           # write the header
    python scripts/gen_firmware_config.py --check   # exit 1 if the header is out of date

sensors.json (limits, hysteresis, direction, enabled, tier, firmware_flag, lcd_name) and
settings.json (hold_seconds) are the single source of truth for the device rules: the
firmware never hard-codes a limit. The header also carries the parity-test vectors (only
compiled with -DPARITY_TEST=1): the two worked examples parsed from docs/DATA_CONTRACT.md
plus FULL_SEQUENCE below, run with the real registry. scripts/firmware_parity.py feeds the
same vectors to device_rules.py and compares the Arduino's answers row by row.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT_DIR, SENSORS_PATH, SETTINGS_PATH  # noqa: E402
from app.registry import Registry  # noqa: E402

CONTRACT_PATH = ROOT_DIR / "docs" / "DATA_CONTRACT.md"
HEADER_PATH = ROOT_DIR / "firmware" / "machine_monitor" / "config_generated.h"

# Multi-sensor parity sequence, run with the real registry (missing key = empty field).
# It covers both directions together, in-band holds, a core fault and an optional empty field.
_BASE = {"temp_c": 29.0, "humidity": 60.0, "sound_peak": 5, "vib_count": 1, "leak_raw": 6, "distance_cm": 150.0}
_NO_DHT = {k: v for k, v in _BASE.items() if k not in ("temp_c", "humidity")}
_NO_DIST = {k: v for k, v in _BASE.items() if k != "distance_cm"}
FULL_SEQUENCE: list[dict[str, float]] = (
    [_BASE]
    + [{**_BASE, "leak_raw": 60}, {**_BASE, "leak_raw": 45}] + [{**_BASE, "leak_raw": 8}] * 5
    + [{**_BASE, "distance_cm": 15.0}, {**_BASE, "distance_cm": 8.0, "vib_count": 70},
       {**_BASE, "distance_cm": 400.0, "vib_count": 70}, {**_BASE, "distance_cm": 400.0, "vib_count": 58}]
    + [{**_BASE, "distance_cm": 400.0}] * 5
    + [_NO_DHT] + [_BASE] * 5
    + [{**_BASE, "sound_peak": 130, "leak_raw": 250}, {**_NO_DIST, "sound_peak": 130}]
    + [{**_NO_DIST, "humidity": 85.0, "temp_c": 34.6}] + [_BASE] * 6
)


@dataclass
class Example:
    """One worked example table: a single sensor run through the state machine."""
    name: str
    key: str
    direction: str
    warn: float
    critical: float
    h: float
    hold: int
    steps: list[tuple[int, float | None, str]]   # (row, value or None for empty, expected state)


def parse_examples(doc: str) -> list[Example]:
    """Every '#### Worked example' table in DATA_CONTRACT.md."""
    out = []
    for i, section in enumerate(doc.split("#### Worked example")[1:], 1):
        heading = section.splitlines()[0]
        key = re.search(r"`(\w+)`", heading).group(1)
        params = {k: float(v) for k, v in re.findall(r"\b(warn|critical|h|hold) ([\d.]+)", heading)}
        direction = m.group(1) if (m := re.search(r"direction (above|below)", heading)) else "above"
        lines = section.splitlines()
        start = next(j for j, l in enumerate(lines) if l.startswith("|"))
        end = next((j for j in range(start, len(lines)) if not lines[j].startswith("|")), len(lines))
        table = lines[start + 2:end]                     # the first table only, without header rows
        steps = []
        for line in table:
            rows_cell, value_cell, state_cell = [c.strip() for c in line.strip("|").split("|")][:3]
            lo, _, hi = rows_cell.replace("–", "-").partition("-")
            lo, hi = int(lo), int(hi or lo)
            value = None if value_cell == "empty" else float(value_cell)
            states = re.findall(r"`(NORMAL|WARNING|CRITICAL)`", state_cell)
            at = re.search(r"at row (\d+)", state_cell)
            for row in range(lo, hi + 1):
                steps.append((row, value, states[1] if at and row >= int(at.group(1)) else states[0]))
        out.append(Example(f"example{i}", key, direction, params["warn"], params["critical"], params["h"],
                           int(params["hold"]), steps))
    return out


def example_registry(ex: Example, sensors_data: dict) -> Registry:
    """A one-sensor registry: the real entry for ex.key with the example's limits."""
    entry = next(s for s in sensors_data["sensors"] if s["key"] == ex.key)
    entry = {**entry, "warn": ex.warn, "critical": ex.critical, "hysteresis": ex.h,
             "direction": ex.direction, "enabled": True, "group": None}
    return Registry.from_dict({"csv_columns": ["ms", ex.key, "dev_state"], "sensors": [entry]})


def parity_cases(sensors_data: dict, hold_seconds: int, doc: str) -> list[tuple[str, Registry, int, list[dict]]]:
    """(name, registry, hold, rows) for every parity case, in firmware order."""
    cases = [(ex.name, example_registry(ex, sensors_data), ex.hold,
              [{ex.key: v} for _, v, _ in ex.steps]) for ex in parse_examples(doc)]
    cases.append(("full", Registry.from_dict(sensors_data), hold_seconds, FULL_SEQUENCE))
    return cases


# ---- rendering ------------------------------------------------------------------------------

def _f(x: float | None) -> str:
    return "0.0f" if x is None else f"{float(x)!r}f"


def _rules(reg: Registry, name: str) -> list[str]:
    lines = [f"static const SensorRule {name}[{len(reg.sensors)}] = {{"]
    for s in reg.sensors:
        flags = ["0"]
        if s.warn is not None:
            flags.append("RULE_HAS_WARN")
        if s.critical is not None:
            flags.append("RULE_HAS_CRIT")
        if s.direction == "below":
            flags.append("RULE_BELOW")
        if s.is_core:
            flags.append("RULE_CORE")
        if s.enabled:
            flags.append("RULE_ENABLED")
        flag_text = " | ".join(flags[1:]) or "0"
        lines.append(f"  {{{_f(s.warn)}, {_f(s.critical)}, {_f(s.hysteresis)}, {flag_text}}},  // {s.key} ({s.tier})")
    lines.append("};")
    return lines


def render(sensors_data: dict, settings: dict, doc: str) -> str:
    reg = Registry.from_dict(sensors_data)
    if reg.warnings:
        raise SystemExit("sensors.json has problems, fix them first:\n  " + "\n  ".join(reg.warnings))
    hold = int(settings.get("hold_seconds", 5))
    raw = {s["key"]: s for s in sensors_data["sensors"]}
    flags: dict[str, bool] = {}
    for s in reg.sensors:
        flag = raw[s.key].get("firmware_flag")
        if not flag or not re.fullmatch(r"USE_[A-Z0-9_]+", flag):
            raise SystemExit(f"{s.key}: firmware_flag must look like USE_<SENSOR>, got {flag!r}")
        if flags.setdefault(flag, s.enabled) != s.enabled:
            raise SystemExit(f"{flag}: sensors sharing this flag disagree on 'enabled'")
    columns = reg.csv_columns
    if [c for c in columns[1:-1]] != reg.sensor_keys:
        raise SystemExit("csv_columns must list the sensors in registry order (ms first, dev_state last)")

    L = [
        "// GENERATED - do not edit, run gen_firmware_config.py",
        "// (backend\\venv\\Scripts\\python backend\\scripts\\gen_firmware_config.py, from the repo root)",
        "// Source: backend/config/sensors.json + backend/config/settings.json",
        "//         (+ the worked examples in docs/DATA_CONTRACT.md for the parity test).",
        "#pragma once",
        "",
        '#include "state_machine.h"',
        "",
        f'#define CSV_HEADER "# {",".join(columns)}"',
        f"#define SENSOR_COUNT {len(reg.sensors)}",
        f"#define HOLD_SECONDS {hold}",
        "",
        "// Fitted modules (sensors.json 'enabled'; 1 = read it, 0 = print an empty field).",
    ]
    for flag, on in flags.items():
        keys = ", ".join(s.key for s in reg.sensors if raw[s.key]["firmware_flag"] == flag)
        L.append(f"#define {flag + ' ' * max(1, 14 - len(flag))}{int(on)}  // {keys}")
    L += ["", "// Column index of each sensor in the values array (CSV order without ms/dev_state)."]
    for i, s in enumerate(reg.sensors):
        L.append(f"#define IDX_{s.key.upper()} {i}")
    oor = [s for s in reg.sensors if s.out_of_range_value is not None]
    if oor:
        L += ["", "// 'Nothing in range' readings (a real, clear value, not a fault)."]
        for s in oor:
            L.append(f"#define {s.key.upper()}_OUT_OF_RANGE {_f(s.out_of_range_value)}")
    L += ["", "// Limits: {warn, critical, hysteresis, flags}. Tier core/optional = RULE_CORE."]
    L += _rules(reg, "SENSOR_RULES")
    L += ["", "// Short LCD names (lcd_name) and module names for 'SENSOR FAULT' (hardware)."]
    for s in reg.sensors:
        lcd = raw[s.key].get("lcd_name") or s.key[:4].upper()
        if len(lcd) > 4:
            raise SystemExit(f"{s.key}: lcd_name {lcd!r} is longer than 4 characters")
        hw = (s.hardware or s.key).split(" (")[0]
        if len(hw) > 16:
            hw = hw[:17].rsplit(" ", 1)[0][:16]          # cut at a word: "Water leak"
        L.append(f'static const char LCD_NAME_{s.key.upper()}[] PROGMEM = "{lcd}";')
        L.append(f'static const char HW_NAME_{s.key.upper()}[] PROGMEM = "{hw}";')
    L.append(f"static const char* const LCD_NAMES[SENSOR_COUNT] PROGMEM = {{"
             + ", ".join(f"LCD_NAME_{s.key.upper()}" for s in reg.sensors) + "};")
    L.append(f"static const char* const HW_NAMES[SENSOR_COUNT] PROGMEM = {{"
             + ", ".join(f"HW_NAME_{s.key.upper()}" for s in reg.sensors) + "};")

    # ---- parity vectors
    L += ["", "#if PARITY_TEST", "// Parity cases: rows of values (NAN = empty field), run through StateMachine at boot."]
    names = []
    for name, creg, chold, rows in parity_cases(sensors_data, hold, doc):
        cname = name.upper()
        n = len(creg.sensors)
        if name != "full":
            L += _rules(creg, f"PARITY_RULES_{cname}")
        rules = "SENSOR_RULES" if name == "full" else f"PARITY_RULES_{cname}"
        L.append(f"static const float PARITY_VALUES_{cname}[{len(rows) * n}] PROGMEM = {{")
        for r in rows:
            L.append("  " + ", ".join("NAN" if r.get(s.key) is None else _f(r[s.key]) for s in creg.sensors) + ",")
        L.append("};")
        names.append(f'  {{"{name}", {rules}, {n}, {chold}, PARITY_VALUES_{cname}, {len(rows)}}},')
    L += ["struct ParityCase { const char* name; const SensorRule* rules; uint8_t count; uint8_t hold;",
          "                    const float* values; uint8_t rows; };",
          f"static const ParityCase PARITY_CASES[{len(names)}] = {{", *names, "};",
          f"#define PARITY_CASE_COUNT {len(names)}", "#endif  // PARITY_TEST", ""]
    return "\n".join(L)


def load_inputs() -> tuple[dict, dict, str]:
    return (json.loads(SENSORS_PATH.read_text(encoding="utf-8")),
            json.loads(SETTINGS_PATH.read_text(encoding="utf-8")),
            CONTRACT_PATH.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only check that the header is up to date")
    args = ap.parse_args(argv)
    text = render(*load_inputs())
    current = HEADER_PATH.read_text(encoding="utf-8") if HEADER_PATH.exists() else None
    if args.check:
        if current != text:
            print(f"{HEADER_PATH} is out of date: run scripts/gen_firmware_config.py", file=sys.stderr)
            return 1
        print("config_generated.h is up to date")
        return 0
    if current == text:
        print(f"{HEADER_PATH.name} already up to date")
    else:
        HEADER_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEADER_PATH.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {HEADER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
