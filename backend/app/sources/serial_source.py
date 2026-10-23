"""Live data from the Arduino over USB serial.

- Finds the port automatically (Arduino VID first, then USB-serial chip names), falling
  back to settings.serial_port / the MHM_PORT environment variable.
- Survives unplugging: reports connected=False and retries every reconnect_interval_s.
- A port held by another program (e.g. the Arduino IDE Serial Monitor) is reported as
  "port busy" in the status instead of crashing.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Callable

import serial
from serial.tools import list_ports

from ..config import Settings
from ..models import SensorRow, parse_line
from .base import Source

log = logging.getLogger(__name__)

ARDUINO_VIDS = {0x2341}  # Arduino LLC (genuine Uno with ATmega16U2)
NAME_HINTS = ("arduino", "ch340", "usb-serial")


def detect_arduino_port() -> str | None:
    """Auto-detect only: return the first port that looks like an Arduino, else None."""
    ports = list(list_ports.comports())
    for p in ports:
        if p.vid in ARDUINO_VIDS:
            return p.device
    for p in ports:
        text = f"{p.description or ''} {p.manufacturer or ''}".lower()
        if any(h in text for h in NAME_HINTS):
            return p.device
    return None


def port_exists(port: str) -> bool:
    return any(p.device.lower() == port.lower() for p in list_ports.comports())


def resolve_port(settings: Settings) -> tuple[str | None, str]:
    """(port, how it was chosen). Priority: MHM_PORT > auto-detect > settings.json."""
    if settings.env_port:
        return settings.env_port, "MHM_PORT environment variable"
    port = detect_arduino_port()
    if port:
        return port, "auto-detected"
    if settings.serial_port:
        return settings.serial_port, "settings.json serial_port"
    return None, "not found"


def _is_busy_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(s in text for s in ("permissionerror", "access is denied", "busy", "errno 13", "errno 16"))


class SerialSource(Source):
    kind = "serial"

    def __init__(self, *args: Any, settings: Settings, label_getter: Callable[[], str] | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.settings = settings
        self.label_getter = label_getter or (lambda: "unknown")
        self.port: str | None = None
        self.port_how: str | None = None
        self._ser: serial.Serial | None = None

    def _open(self, port: str) -> serial.Serial:
        return serial.Serial(port, self.settings.baud, timeout=1)

    async def rows(self) -> AsyncIterator[SensorRow]:
        retry = self.settings.reconnect_interval_s
        while True:
            port, how = resolve_port(self.settings)
            if port != self.port:
                self.port, self.port_how = port, how
                log.info("Serial port: %s (%s)", port, how)
                if self.on_change:
                    await self.on_change()
            if port is None:
                await self._set_status(connected=False, error="No Arduino found. Plug in the USB cable or set MHM_PORT.")
                await asyncio.sleep(retry)
                continue

            try:
                self._ser = await asyncio.to_thread(self._open, port)
            except (serial.SerialException, OSError) as exc:
                if _is_busy_error(exc):
                    msg = f"{port} busy, close Serial Monitor (or any other program using the port)"
                else:
                    msg = f"Cannot open {port}: {exc}"
                await self._set_status(connected=False, error=msg)
                await asyncio.sleep(retry)
                continue

            log.info("Opened %s (%s) at %d baud", port, how, self.settings.baud)
            try:
                # Opening the port resets the Uno; give it time to boot.
                await asyncio.sleep(self.settings.serial_boot_wait_s)
                await self._set_status(connected=True, error=None)
                first = True
                while True:
                    raw = await asyncio.to_thread(self._ser.readline)
                    if not raw:
                        continue  # 1 s timeout with no data; keep waiting
                    line = raw.decode("ascii", errors="replace")
                    if first and not line.lstrip().startswith("#"):
                        first = False  # may be a partial line from before we started reading
                        continue
                    first = False
                    row = parse_line(line, self.registry, self.stats,
                                     mode="live", source="real", label=self.label_getter())
                    if row is not None:
                        yield row
            except (serial.SerialException, OSError) as exc:
                log.warning("Serial connection on %s lost: %s", port, exc)
                await self._set_status(connected=False, error=f"Connection on {port} lost (cable unplugged?). Retrying...")
            finally:
                await self.close()
            await asyncio.sleep(retry)

    async def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001 - closing a dead port must never crash
                pass

    def status(self) -> dict[str, Any]:
        return {**super().status(), "serial_port": self.port, "port_found": self.port_how}
