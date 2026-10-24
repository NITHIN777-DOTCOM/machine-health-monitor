"""Entry point of the portable app (MachineHealthMonitor.exe): start the server, open the browser.

    MachineHealthMonitor.exe                 Arduino if one is plugged in, else the simulator
    MachineHealthMonitor.exe --simulator     simulator only, never opens a COM port (= MHM_SOURCE=simulator)
    MachineHealthMonitor.exe --port 8050     first port to try (default 8000)
    MachineHealthMonitor.exe --no-browser    don't open the browser

1. If this app is already running on one of the ports (8000-8010), open the browser to it
   and exit, so a second double-click never starts a second server.
2. Otherwise take the first free port from --port up to 8010 (or --port + 10), bind it,
   and run uvicorn on 127.0.0.1 only (nothing is reachable from the network).
3. Once /api/status answers, print a short banner and open the browser.

Logs: the console shows the banner and warnings; everything (INFO and up) also goes to
logs/mhm_YYYYMMDD.log next to the exe. Closing the console window stops the server.
Also runs unfrozen: `python -m app.launcher` from backend/.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import logging
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from datetime import datetime

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
LAST_PORT = 8010
READY_TIMEOUT_S = 60.0

log = logging.getLogger("mhm.launcher")
_stopped = threading.Event()          # set once uvicorn has shut down
_close_handler = None                 # the console handler; kept referenced so it isn't freed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="MachineHealthMonitor",
                                 description="Predictive Machine Health Monitor: backend + dashboard.")
    ap.add_argument("--simulator", action="store_true",
                    help="simulator only: never open a COM port (same as MHM_SOURCE=simulator)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"first port to try (default {DEFAULT_PORT})")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    return ap.parse_args(argv)


def candidate_ports(first: int) -> list[int]:
    """--port 8000 -> 8000..8010; a port above that -> that port and the next 10."""
    return list(range(first, max(LAST_PORT, first + 10) + 1))


# ---- finding an instance / a free port --------------------------------------------------

def probe(port: int, timeout: float = 0.5) -> dict | None:
    """/api/status of the server on this port if it is this app, else None."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/status", timeout=timeout) as r:
            status = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    from .version import APP_ID
    return status if isinstance(status, dict) and (status.get("version") or {}).get("app") == APP_ID else None


def find_instance(ports: list[int]) -> int | None:
    for port in ports:
        if _listening(port) and probe(port) is not None:
            return port
    return None


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((HOST, port)) == 0


def bind_free_port(ports: list[int]) -> tuple[socket.socket, int, list[int]]:
    """Bind the first free port; returns (socket, port, ports skipped as busy). The socket
    is handed to uvicorn, so no other program can take the port in between."""
    busy = []
    for port in ports:
        if _listening(port):            # e.g. another server on 0.0.0.0:port
            busy.append(port)
            continue
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):   # Windows: never share a port
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind((HOST, port))
        except OSError:
            sock.close()
            busy.append(port)
            continue
        sock.listen(128)
        sock.set_inheritable(True)
        return sock, port, busy
    raise OSError(f"ports {ports[0]}-{ports[-1]} are all busy; close the program using them or pass --port")


# ---- logging, banner, console --------------------------------------------------------------

def setup_logging() -> str | None:
    """Console: warnings and up (the banner stays readable). File: INFO and up."""
    from . import paths
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(console)
    try:
        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_path = paths.LOGS_DIR / f"mhm_{datetime.now():%Y%m%d}.log"
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
        return str(log_path)
    except OSError as exc:            # read-only folder (e.g. a locked pendrive): console only
        log.warning("No log file (%s)", exc)
        return None


def source_text(status: dict) -> str:
    """"Arduino on COM5" / "Simulator (no Arduino found)" / ... from /api/status."""
    if status.get("source") == "serial":
        return f"Arduino on {status.get('serial_port') or '?'}"
    reason = status.get("startup_reason") or ""
    if reason.startswith("MHM_SOURCE=simulator"):
        why = "simulator only; serial disabled"
    elif "no Arduino" in reason:
        why = "no Arduino found"
    else:
        why = reason.split(";")[0] or status.get("source") or "?"
    return f"Simulator ({why})"


def banner(url: str, status: dict, log_path: str | None, busy: list[int]) -> str:
    from . import paths
    from .version import APP_NAME, version_text
    lines = [
        f"  {APP_NAME}   {version_text()}",
        "",
        f"  Dashboard:    {url}",
        f"  Data source:  {source_text(status)}",
        f"  Recordings:   {paths.RECORDINGS_DIR}",
        f"  Log file:     {log_path or 'none (folder not writable)'}",
    ]
    if busy:
        lines.append(f"  (port {', '.join(map(str, busy))} busy, so this copy uses {url.rstrip('/').rsplit(':', 1)[1]})")
    lines += ["", "  Close this window to stop."]
    bar = "=" * 72
    return "\n".join([bar, *lines, bar])


def _keep_console_open() -> None:
    """After a fatal error, wait so a double-clicked window doesn't vanish before it is read."""
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close this window.")
    except (EOFError, OSError):
        pass


def _install_close_handler(server) -> None:
    """Closing the console window (or logging off) stops uvicorn cleanly, so an active
    recording is closed. Windows ends the process a few seconds after this returns anyway."""
    if os.name != "nt":
        return
    CLOSE_EVENTS = (2, 5, 6)          # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT

    global _close_handler

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
    def handler(event: int) -> bool:
        if event not in CLOSE_EVENTS:
            return False              # Ctrl+C / Ctrl+Break: uvicorn's own handler
        server.should_exit = True
        _stopped.wait(3)
        return True

    _close_handler = handler
    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)


# ---- main ------------------------------------------------------------------------------------

def _wait_ready_then_announce(port: int, open_browser: bool, log_path: str | None, busy: list[int],
                              t0: float) -> None:
    url = f"http://{HOST}:{port}/"
    end = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < end:
        status = probe(port, timeout=1.0)
        if status is not None:
            print(banner(url, status, log_path, busy), flush=True)
            log.info("Ready at %s in %.1f s (source: %s)", url, time.perf_counter() - t0, source_text(status))
            if open_browser:
                webbrowser.open(url)
            return
        time.sleep(0.2)
    log.warning("The server did not answer within %.0f s; open %s by hand", READY_TIMEOUT_S, url)


def main(argv: list[str] | None = None) -> int:
    t0 = time.perf_counter()
    args = parse_args(argv)
    if args.simulator:
        os.environ["MHM_SOURCE"] = "simulator"
    log_path = setup_logging()
    from .version import APP_NAME, version_text
    print(f"Starting {APP_NAME} {version_text()} ...", flush=True)
    log.info("Starting %s %s (args: %s)", APP_NAME, version_text(), " ".join(sys.argv[1:]) or "none")

    ports = candidate_ports(args.port)
    running = find_instance(ports)
    if running is not None:
        url = f"http://{HOST}:{running}/"
        print(f"\nAlready running at {url}; opening the browser there instead of starting a second copy.")
        log.info("Instance already running at %s; not starting another", url)
        if not args.no_browser:
            webbrowser.open(url)
        time.sleep(4)                  # long enough to read the message
        return 0

    import uvicorn

    from . import paths
    for copied in paths.ensure_app_dirs():
        log.info("First run: copied default %s", copied)
    from .main import app             # the slow part (numpy, sklearn): done before taking the port

    # Bind only now: a port bound during the import above would queue connections nobody accepts.
    try:
        sock, port, busy = bind_free_port(ports)
    except OSError as exc:
        log.error("%s", exc)
        _keep_console_open()
        return 2
    if busy:
        log.warning("Port %s busy (another program); using %d", ", ".join(map(str, busy)), port)

    config = uvicorn.Config(app, host=HOST, port=port, log_config=None, access_log=False,
                            ws_ping_interval=20, timeout_graceful_shutdown=3)
    server = uvicorn.Server(config)
    _install_close_handler(server)
    threading.Thread(target=_wait_ready_then_announce, args=(port, not args.no_browser, log_path, busy, t0),
                     daemon=True, name="announce").start()
    try:
        # Selector loop, not Windows' default Proactor: on Python 3.11 the Proactor stops
        # accepting for good (and closes the port) when a client gives up on a queued
        # connection (WinError 64). The app only needs sockets and threads, which the
        # selector loop supports.
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(server.serve(sockets=[sock]))
    finally:
        sock.close()
        _stopped.set()
    log.info("Stopped")
    return 0


def run() -> None:
    """Exe entry: never let a crash close the window before the user can read it."""
    try:
        code = main()
    except SystemExit:
        raise
    except KeyboardInterrupt:         # Ctrl+C: uvicorn has already shut down cleanly
        code = 0
    except BaseException:              # noqa: BLE001 - show anything, then exit non-zero
        traceback.print_exc()
        logging.getLogger("mhm.launcher").error("Fatal error:\n%s", traceback.format_exc())
        _keep_console_open()
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    run()
