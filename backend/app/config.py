"""Paths and runtime settings.

Settings come from backend/config/settings.json, plus environment variables:
    MHM_PORT   serial port to use (e.g. COM5); overrides auto-detection.
               Port priority: MHM_PORT > auto-detect > settings.json "serial_port".
    MHM_SOURCE "simulator": start on the simulator and never open (or even list) a serial
               port; POST /api/source {"type": "serial"} is refused. For working on the
               software while another program uses the Arduino's COM port.
    MHM_ROOT   writable root folder (the repo in development, the exe folder when portable)

Where each file lives (repo vs next to the exe) is decided in paths.py.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

ROOT_DIR = paths.APP_DIR
CONFIG_DIR = paths.CONFIG_DIR
SENSORS_PATH = CONFIG_DIR / "sensors.json"
SIM_PROFILE_PATH = CONFIG_DIR / "sim_profile.json"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
RECORDINGS_DIR = paths.RECORDINGS_DIR
MODELS_DIR = paths.MODELS_DIR
FORCEABLE_SOURCES = ("simulator",)   # values MHM_SOURCE accepts


@dataclass
class Settings:
    serial_port: str | None = None   # from settings.json; last resort after auto-detect
    env_port: str | None = None      # from MHM_PORT; overrides auto-detect
    force_source: str | None = None  # from MHM_SOURCE; "simulator" = serial disabled
    baud: int = 115200
    serial_boot_wait_s: float = 2.0
    reconnect_interval_s: float = 2.0
    history_seconds: int = 600
    hold_seconds: int = 5            # device state: rows a level must stay clear before stepping down
    link_grace_s: float = 3.0        # seconds without data (or with a port error) before "disconnected"
    ml_window_s: int = 10            # ML feature window, device-clock seconds
    ml_max_missing_frac: float = 0.3 # a sensor missing in more than this share of the window -> warming up
    forecast_window_s: int = 60      # forecast: linear fit over this many device-clock seconds
    forecast_min_r2: float = 0.6     # forecast: minimum fit quality to report a time-to-limit
    forecast_cap_s: int = 1800       # forecast: longer predictions are shown as "> 30 min"
    ml_anomaly_health: float = 50    # ML ANOMALY after health < this ...
    ml_anomaly_rows: int = 3         # ... for this many consecutive rows
    ml_clear_health: float = 60      # ANOMALY clears after health > this ...
    ml_clear_rows: int = 5           # ... for this many consecutive rows
    warmstart_file: str | None = None  # recording (in data/recordings) to warm-start from on startup
    max_speed: float = 20.0
    recordings_dir: Path = field(default=RECORDINGS_DIR)
    models_dir: Path = field(default=MODELS_DIR)
    demo_dir: Path | None = None     # read-only demo recordings (data/demo), listed after recordings_dir
    evaluation_file: Path = field(default=paths.EVALUATION_FILE)   # GET /api/model/evaluation

    @property
    def recording_dirs(self) -> list[Path]:
        """Where replay / warm start / training look for a recording by name."""
        return [self.recordings_dir] + ([self.demo_dir] if self.demo_dir else [])

    @property
    def manifest_file(self) -> Path:
        """Data roles (train/test) of the recordings, ml/roles.py."""
        return self.recordings_dir / paths.MANIFEST_FILE.name


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    """Load settings; a missing or broken file falls back to defaults (never raises)."""
    settings = Settings(demo_dir=paths.DEMO_DIR)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in data.items():
            if hasattr(settings, key) and key not in ("recordings_dir", "models_dir", "demo_dir", "evaluation_file", "env_port", "force_source"):
                setattr(settings, key, value)
            else:
                log.warning("settings.json: unknown key %r ignored", key)
    except FileNotFoundError:
        log.info("No %s, using default settings", path.name)
    except (OSError, ValueError) as exc:
        log.error("Could not read %s (%s), using default settings", path, exc)

    settings.env_port = os.environ.get("MHM_PORT", "").strip() or None
    forced = os.environ.get("MHM_SOURCE", "").strip().lower() or None
    if forced not in (None, *FORCEABLE_SOURCES):
        log.warning("MHM_SOURCE=%r ignored; the only supported value is 'simulator'", forced)
        forced = None
    settings.force_source = forced
    return settings
