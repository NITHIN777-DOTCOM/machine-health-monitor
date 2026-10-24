"""Where files live, both in the repo (development) and in the portable exe (PyInstaller).

Two kinds of files:

- **Bundled, read-only resources**: the built dashboard, the default configs and the
  shipped model. Frozen: inside the bundle (``sys._MEIPASS``, the ``_internal/`` folder).
  Development: the repo.
- **Writable files**: config the user may edit, recordings, retrained models, logs.
  Frozen: next to ``MachineHealthMonitor.exe``. Development: the repo, as before.

  =================  ==============================  ===============================
  what               development (repo)              portable (next to the exe)
  =================  ==============================  ===============================
  config             backend/config/                 config/
  model              models/                         models/
  recordings         data/recordings/                data/recordings/
  demo recordings    data/demo/                      data/demo/
  logs               logs/                           logs/
  dashboard (r/o)    dashboard/dist/                 _internal/dashboard/dist/
  =================  ==============================  ===============================

On the first frozen run, ensure_app_dirs() copies the default config and model next to the
exe if they are missing, so a user can edit settings.json or sensors.json there.

Every path is derived from this file or the exe location; nothing is absolute, so the
folder can be moved, renamed or run from a pendrive (spaces in the path are fine).
MHM_ROOT (environment variable) overrides the writable root, mainly for tests.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

# The repo root (the folder containing backend/, data/, models/). Only meaningful unfrozen.
REPO_DIR = Path(__file__).resolve().parents[2]
# Read-only resources: the PyInstaller bundle when frozen, else the repo.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", REPO_DIR))
# Writable root: next to the exe when frozen, else the repo.
APP_DIR = Path(os.environ.get("MHM_ROOT") or (Path(sys.executable).resolve().parent if FROZEN else REPO_DIR))

# ---- bundled, read-only ----------------------------------------------------------------
DEFAULT_CONFIG_DIR = BUNDLE_DIR / "backend" / "config"
DEFAULT_MODELS_DIR = BUNDLE_DIR / "models"
DASHBOARD_DIR = BUNDLE_DIR / "dashboard" / "dist"
VERSION_FILE = BUNDLE_DIR / "version.json"     # written by the build; absent in development

# ---- writable --------------------------------------------------------------------------
CONFIG_DIR = APP_DIR / "config" if FROZEN else APP_DIR / "backend" / "config"
MODELS_DIR = APP_DIR / "models"
RECORDINGS_DIR = APP_DIR / "data" / "recordings"
MANIFEST_FILE = RECORDINGS_DIR / "MANIFEST.json"   # data roles (train/test), ml/roles.py
DEMO_DIR = APP_DIR / "data" / "demo"
LOGS_DIR = APP_DIR / "logs"

CONFIG_FILES = ("settings.json", "sensors.json", "sim_profile.json")
MODEL_FILES = ("model.joblib", "model_meta.json")


def ensure_app_dirs() -> list[Path]:
    """Create the writable folders and copy missing defaults into them. Returns the files
    copied. Never overwrites: a user's edited config or retrained model always wins.
    In development the defaults *are* the writable files, so nothing is copied."""
    for d in (CONFIG_DIR, MODELS_DIR, RECORDINGS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in CONFIG_FILES:
        copied += _copy_missing(DEFAULT_CONFIG_DIR / name, CONFIG_DIR / name)
    # The model and its meta belong together: copy both only when there is no model at all.
    if not (MODELS_DIR / MODEL_FILES[0]).exists():
        for name in MODEL_FILES:
            copied += _copy_missing(DEFAULT_MODELS_DIR / name, MODELS_DIR / name)
    return copied


def _copy_missing(src: Path, dst: Path) -> list[Path]:
    if dst.exists() or not src.is_file() or src.resolve() == dst.resolve():
        return []
    shutil.copy2(src, dst)
    return [dst]
