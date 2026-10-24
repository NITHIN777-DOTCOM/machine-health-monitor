"""SerialSource with a fake serial port (no hardware) and port selection with mocked list_ports."""
import asyncio
import logging
import time
from types import SimpleNamespace

import pytest
import serial

from app.config import Settings, load_settings
from app.models import ParseStats
from app.sources import serial_source
from app.sources.serial_source import SerialSource, detect_arduino_port, resolve_port
from helpers import collapse, collect

HEADER = b"# ms,temp_c,humidity,sound_peak,vib_count,leak_raw,distance_cm,current_ma,bus_v,dev_state\r\n"


def line(ms, temp=29.0, state="NORMAL"):
    return f"{ms},{temp},60.0,5,1,,,,,{state}\r\n".encode()


class FakeSerial:
    """Returns queued lines, then either raises (cable pulled) or idles like a 1 s timeout.
    `stale` lines are already buffered when the port opens (until reset_input_buffer)."""

    def __init__(self, lines, then="idle", stale=()):
        self.lines = list(lines)
        self.stale = list(stale)
        self.then = then
        self.closed = False
        self.flushed = False

    def reset_input_buffer(self):
        self.stale.clear()
        self.flushed = True

    def readline(self):
        if self.stale:
            return self.stale.pop(0)
        if self.lines:
            return self.lines.pop(0)
        if self.then == "disconnect":
            raise serial.SerialException("ClearCommError failed (device disconnected)")
        time.sleep(0.01)
        return b""

    def close(self):
        self.closed = True


def make_source(registry, opens, events=None, label_getter=None):
    """SerialSource whose _open() returns/raises the given items in order."""
    async def on_change():
        if events is not None:
            events.append((src.connected, src.last_error))

    settings = Settings(env_port="COM_TEST", serial_boot_wait_s=0, reconnect_interval_s=0.01)
    src = SerialSource(registry=registry, stats=ParseStats(), on_change=on_change,
                       settings=settings, label_getter=label_getter)
    queue = list(opens)

    def fake_open(port):
        item = queue.pop(0) if queue else FakeSerial([])
        if isinstance(item, Exception):
            raise item
        return item

    src._open = fake_open
    return src


def test_partial_first_line_dropped_and_header_recognised(registry, caplog):
    # The first line looks complete but may have been cut off; it must be dropped, not parsed.
    fake = FakeSerial([line(999), HEADER, line(1000), line(2000)])
    src = make_source(registry, [fake])
    with caplog.at_level(logging.INFO):
        rows = asyncio.run(collect(src, 2))
    assert [r.ms for r in rows] == [1000, 2000]
    assert src.stats.comments == 1 and src.stats.rejected == 0
    assert "Device header matches the registry" in caplog.text
    assert all((r.mode, r.source, r.label) == ("live", "real", "unknown") for r in rows)
    assert fake.closed


def test_output_from_before_the_reset_is_flushed(registry):
    # Bench, Phase 7.1: the board ran with nobody reading; opening the port delivered an old
    # header, 24 old rows and a row cut off by the reset ('25183,29# fw machine_monitor ...').
    stale = [HEADER, line(24183), b"25183,29# fw machine_monitor v1.0.0\r\n"]
    fake = FakeSerial([b"# fw machine_monitor v1.0.0\r\n", HEADER, line(1183), line(2183)], stale=stale)
    src = make_source(registry, [fake])
    rows = asyncio.run(collect(src, 2))
    assert fake.flushed and [r.ms for r in rows] == [1183, 2183]
    assert src.stats.rejected == 0


def test_row_cut_off_by_a_reset_is_dropped_not_rejected(registry, caplog):
    # Bench, Phase 7.1: the row being printed at the reset came out glued to the boot banner.
    cut = b"160183,29.8,81.0,3,0,6,27.4,,,# fw machine_monitor v1.0.0\r\n"
    src = make_source(registry, [FakeSerial([HEADER, line(1000), cut, HEADER, line(1183)])])
    with caplog.at_level(logging.INFO):
        rows = asyncio.run(collect(src, 2))
    assert [r.ms for r in rows] == [1000, 1183]
    assert src.stats.rejected == 0 and src.stats.comments == 3
    assert "cut off by a board reset" in caplog.text


def test_header_as_first_line_is_kept(registry):
    src = make_source(registry, [FakeSerial([HEADER, line(1000)])])
    assert [r.ms for r in asyncio.run(collect(src, 1))] == [1000]
    assert src.stats.comments == 1


def test_garbage_lines_are_counted_as_rejected(registry):
    fake = FakeSerial([HEADER, b"hello world\r\n", b"1000,abc,60,5,1,,,,,NORMAL\r\n",
                       b"\xff\xfe\r\n", line(2000)])
    src = make_source(registry, [fake])
    rows = asyncio.run(collect(src, 1))
    assert [r.ms for r in rows] == [2000]
    assert src.stats.rejected == 3


def test_disconnect_then_reconnect_resumes(registry):
    events = []
    first = FakeSerial([HEADER, line(1000), line(2000)], then="disconnect")
    second = FakeSerial([HEADER, line(1000)])            # Uno resets on reconnect: ms restarts
    src = make_source(registry, [first, second], events)
    rows = asyncio.run(collect(src, 3))
    assert [r.ms for r in rows] == [1000, 2000, 1000]
    # port found (not yet open), connected, cable pulled, connected again
    assert collapse([c for c, _ in events]) == [False, True, False, True]
    lost = next(err for c, err in events if c is False and err)
    assert "lost" in lost and "COM_TEST" in lost
    assert src.connected and src.last_error is None
    assert first.closed


def test_busy_port_reports_clear_error_then_recovers(registry):
    events = []
    busy = serial.SerialException(
        "could not open port 'COM_TEST': PermissionError(13, 'Access is denied.', None, 5)")
    src = make_source(registry, [busy, busy, FakeSerial([HEADER, line(1000)])], events)
    rows = asyncio.run(collect(src, 1))
    assert rows[0].ms == 1000
    errors = [e for _, e in events if e]
    assert errors[0] == "COM_TEST busy, close Serial Monitor (or any other program using the port)"
    assert events[-1] == (True, None)


def test_other_open_errors_are_reported(registry):
    events = []
    missing = serial.SerialException("could not open port 'COM_TEST': FileNotFoundError(2, ...)")
    src = make_source(registry, [missing, FakeSerial([HEADER, line(1000)])], events)
    asyncio.run(collect(src, 1))
    assert next(e for _, e in events if e).startswith("Cannot open COM_TEST")


def test_no_port_found_is_reported(registry, monkeypatch):
    monkeypatch.setattr(serial_source.list_ports, "comports", lambda: [])
    events = []
    src = make_source(registry, [], events)
    src.settings.env_port = None

    async def run():
        task = asyncio.create_task(collect(src, 1, timeout=5))
        await asyncio.sleep(0.1)
        task.cancel()

    asyncio.run(run())
    assert src.connected is False and "No Arduino found" in src.last_error


def test_label_getter_is_applied_per_row(registry):
    labels = iter(["unknown", "fault", "normal"])
    src = make_source(registry, [FakeSerial([HEADER, line(1000), line(2000), line(3000)])],
                      label_getter=lambda: next(labels))
    assert [r.label for r in asyncio.run(collect(src, 3))] == ["unknown", "fault", "normal"]


# ---- port selection ------------------------------------------------------------------

def port(device, vid=None, description="", manufacturer=""):
    return SimpleNamespace(device=device, vid=vid, description=description, manufacturer=manufacturer)


BLUETOOTH = port("COM3", None, "Standard Serial over Bluetooth link")
UNO = port("COM5", 0x2341, "Arduino Uno (COM5)", "Arduino LLC (www.arduino.cc)")
CH340 = port("COM8", 0x1A86, "USB-SERIAL CH340 (COM8)", "wch.cn")


@pytest.fixture
def ports(monkeypatch):
    def _set(*items):
        monkeypatch.setattr(serial_source.list_ports, "comports", lambda: list(items))
    return _set


def test_mhm_port_overrides_auto_detect(ports):
    ports(BLUETOOTH, UNO)
    assert resolve_port(Settings(env_port="COM9", serial_port="COM7")) == ("COM9", "MHM_PORT environment variable")


def test_auto_detect_beats_settings_file(ports):
    ports(BLUETOOTH, UNO)
    assert resolve_port(Settings(serial_port="COM7")) == ("COM5", "auto-detected")


def test_settings_file_is_last_resort(ports):
    ports(BLUETOOTH)
    assert resolve_port(Settings(serial_port="COM7")) == ("COM7", "settings.json serial_port")
    assert resolve_port(Settings()) == (None, "not found")


def test_vid_match_preferred_over_name_match(ports):
    ports(CH340, UNO)
    assert detect_arduino_port() == "COM5"


def test_clone_detected_by_name(ports):
    ports(BLUETOOTH, CH340)
    assert detect_arduino_port() == "COM8"


def test_load_settings_reads_mhm_port(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text('{"serial_port": "COM7", "hold_seconds": 3, "bogus": 1}', encoding="utf-8")
    monkeypatch.setenv("MHM_PORT", " COM9 ")
    s = load_settings(path)
    assert (s.env_port, s.serial_port, s.hold_seconds) == ("COM9", "COM7", 3)
    monkeypatch.delenv("MHM_PORT")
    assert load_settings(path).env_port is None
    assert load_settings(tmp_path / "missing.json").hold_seconds == 5


def test_mhm_source_env(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("MHM_SOURCE", raising=False)
    assert load_settings(path).force_source is None
    monkeypatch.setenv("MHM_SOURCE", " Simulator ")
    assert load_settings(path).force_source == "simulator"
    monkeypatch.setenv("MHM_SOURCE", "serial")          # unsupported: ignored with a warning
    assert load_settings(path).force_source is None
