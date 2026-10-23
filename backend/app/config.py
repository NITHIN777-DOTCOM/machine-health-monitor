"""Paths and runtime settings.

Settings come from backend/config/settings.json, plus environment variables:
    MHM_PORT   serial port to use (e.g. COM5); overrides auto-detection.
               Port priority: MHM_PORT > auto-detect > settings.json "serial_port".
    MHM_ROOT   project root folder (the one containing backend/, data/, models/)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

ROOT_DIR = Path(os.environ.get("MHM_ROOT") or Path(__file__).resolve().parents[2])
BACKEND_DIR = ROOT_DIR / "backend"
CONFIG_DIR = BACKEND_DIR / "config"
SENSORS_PATH = CONFIG_DIR / "sensors.json"
SIM_PROFILE_PATH = CONFIG_DIR / "sim_profile.json"
SETTINGS_PATH = CONFIG_DIR / "settings.json"
RECORDINGS_DIR = ROOT_DIR / "data" / "recordings"
MODELS_DIR = ROOT_DIR / "models"


@dataclass
class Settings:
    serial_port: str | None = None   # from settings.json; last resort after auto-detect
    env_port: str | None = None      # from MHM_PORT; overrides auto-detect
    baud: int = 115200
    serial_boot_wait_s: float = 2.0
    reconnect_interval_s: float = 2.0
    history_seconds: int = 600
    max_speed: float = 20.0
    recordings_dir: Path = field(default=RECORDINGS_DIR)


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    """Load settings; a missing or broken file falls back to defaults (never raises)."""
    settings = Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in data.items():
            if hasattr(settings, key) and key not in ("recordings_dir", "env_port"):
                setattr(settings, key, value)
            else:
                log.warning("settings.json: unknown key %r ignored", key)
    except FileNotFoundError:
        log.info("No %s, using default settings", path.name)
    except (OSError, ValueError) as exc:
        log.error("Could not read %s (%s), using default settings", path, exc)

    settings.env_port = os.environ.get("MHM_PORT", "").strip() or None
    return settings
