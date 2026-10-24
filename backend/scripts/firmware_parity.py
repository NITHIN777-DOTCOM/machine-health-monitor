"""Firmware parity test: the Arduino's state machine must match device_rules.py on every row.

    python scripts/firmware_parity.py [--port COM5] [--no-restore]

1. Checks that firmware/machine_monitor/config_generated.h is up to date.
2. Compiles the sketch with -DPARITY_TEST=1 and uploads it.
3. Reads the "# parity,<case>,<row>,<STATE>,<hold_remaining>,<reason sensor>" lines the board
   prints at boot (the cases are the worked examples in docs/DATA_CONTRACT.md and
   gen_firmware_config.FULL_SEQUENCE).
4. Runs the same rows through DeviceStateMachine and compares state, hold countdown and the
   first reason's sensor, row by row.
5. Re-uploads the normal build (always, also after a mismatch; --no-restore skips it).

Needs arduino-cli on PATH and the COM port free (stop the backend, close the Serial Monitor).
Exit code 0 = every row matches.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import serial  # noqa: E402

import gen_firmware_config as gen  # noqa: E402
from app.config import ROOT_DIR  # noqa: E402
from app.device_rules import DeviceStateMachine  # noqa: E402
from app.sources.serial_source import detect_arduino_port  # noqa: E402

FQBN = "arduino:avr:uno"
SKETCH = ROOT_DIR / "firmware" / "machine_monitor"
BUILD = ROOT_DIR / "firmware" / "build"          # gitignored (build/)
READ_TIMEOUT_S = 25


def arduino(*args: str) -> None:
    cmd = ["arduino-cli", *args]
    print("$", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = (result.stdout + result.stderr).strip()
    for line in out.splitlines():
        if line.startswith(("Sketch uses", "Global variables", "New upload port", "error", "Error")):
            print("  " + line)
    if result.returncode != 0:
        raise SystemExit(f"arduino-cli failed ({result.returncode}):\n{out}")


def build_and_upload(port: str, parity: bool) -> None:
    path = BUILD / ("parity" if parity else "normal")
    extra = ["--build-property", "build.extra_flags=-DPARITY_TEST=1"] if parity else []
    arduino("compile", "--fqbn", FQBN, "--build-path", str(path), *extra, str(SKETCH))
    arduino("upload", "--fqbn", FQBN, "-p", port, "--input-dir", str(path), str(SKETCH))


def read_parity_lines(port: str) -> list[list[str]]:
    rows: list[list[str]] = []
    with serial.Serial(port, 115200, timeout=1) as ser:      # opening the port resets the Uno
        end = time.monotonic() + READ_TIMEOUT_S
        while time.monotonic() < end:
            line = ser.readline().decode("ascii", errors="replace").strip()
            if "# parity," in line:
                fields = line.split("# parity,", 1)[1].split(",")
                if fields[:2] == ["example1", "1"]:
                    rows = []      # a new run: drop a partial one from before the port reset the board
                rows.append(fields)
            elif line.startswith("# parity_done,"):
                expected = int(line.split(",")[1])
                if expected != len(rows):
                    raise SystemExit(f"board reported {expected} rows but {len(rows)} were read")
                return rows
    raise SystemExit(f"no '# parity_done' line within {READ_TIMEOUT_S} s ({len(rows)} parity rows read)")


def expected_rows() -> list[tuple[str, int, str, str, str]]:
    """(case, row, state, hold_remaining or '', first reason sensor index or '') from device_rules.py."""
    sensors, settings, doc = gen.load_inputs()
    out = []
    for name, reg, hold, rows in gen.parity_cases(sensors, int(settings["hold_seconds"]), doc):
        index = {s.key: i for i, s in enumerate(reg.sensors)}
        sm = DeviceStateMachine(reg, hold)
        for n, values in enumerate(rows, 1):
            state = sm.update({k: values.get(k) for k in reg.sensor_keys})
            hold_left = sm.hold_remaining_s
            reason = str(index[sm.reasons[0].sensor]) if sm.reasons else ""
            out.append((name, n, state, "" if hold_left is None else str(hold_left), reason))
    return out


def compare(board: list[list[str]]) -> int:
    expected = expected_rows()
    if len(board) != len(expected):
        print(f"MISMATCH: board printed {len(board)} rows, device_rules.py has {len(expected)}")
        return 1
    bad = 0
    print(f"\n{'case':9} {'row':>3}  {'python':22} {'arduino':22}")
    for exp, got in zip(expected, board):
        e = (exp[0], str(exp[1]), *exp[2:])
        g = tuple(got[:5])
        ok = e == g
        bad += not ok
        fmt = lambda t: f"{t[2]:8} hold={t[3] or '-':2} r={t[4] or '-'}"   # noqa: E731
        print(f"{e[0]:9} {e[1]:>3}  {fmt(e):22} {fmt(g):22} {'ok' if ok else '<-- MISMATCH'}")
    cases = sorted({e[0] for e in expected})
    print(f"\n{len(expected) - bad}/{len(expected)} rows match ({', '.join(cases)})")
    return 0 if bad == 0 else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port (default: auto-detect the Uno)")
    ap.add_argument("--no-restore", action="store_true", help="leave the parity build on the board")
    args = ap.parse_args(argv)

    if gen.main(["--check"]) != 0:
        return 2
    port = args.port or detect_arduino_port()
    if not port:
        print("No Arduino found; pass --port", file=sys.stderr)
        return 2
    try:
        build_and_upload(port, parity=True)
        board = read_parity_lines(port)
        code = compare(board)
    finally:
        if not args.no_restore:
            print("\nRe-uploading the normal build...")
            build_and_upload(port, parity=False)
    print("PARITY OK" if code == 0 else "PARITY FAILED")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
