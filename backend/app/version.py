"""App version, shown in /api/status, the dashboard footer and the launcher banner.

The portable build writes version.json into the bundle (packaging/build_release.py):
{"version", "git", "build_date"}. In development the git part comes from `git describe`
and build_date is null.
"""
from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from typing import Any

from . import paths

APP_NAME = "Predictive Machine Health Monitor"
APP_ID = "machine-health-monitor"      # lets the launcher recognise an instance already running
VERSION = "0.6.0"


@lru_cache(maxsize=1)
def version_info() -> dict[str, Any]:
    info: dict[str, Any] = {"app": APP_ID, "name": APP_NAME, "version": VERSION, "git": None,
                            "build_date": None, "frozen": paths.FROZEN}
    try:
        info.update({k: v for k, v in json.loads(paths.VERSION_FILE.read_text(encoding="utf-8")).items()
                     if k in ("version", "git", "build_date")})
    except (OSError, ValueError):
        info["git"] = git_describe()
    return info


def git_describe() -> str | None:
    """"v0.6.0", "v0.6.0-3-gabc1234-dirty" or a bare hash; None without git or a repo."""
    try:
        out = subprocess.run(["git", "describe", "--tags", "--always", "--dirty"], cwd=paths.REPO_DIR,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def version_text() -> str:
    """"v0.6.0 (v0.6.0-0-gabc1234, built 2026-10-24)"; in development "v0.6.0 (abc1234-dirty)"."""
    v = version_info()
    extra = [x for x in (v["git"], v["build_date"] and f"built {v['build_date']}") if x]
    return f"v{v['version']}" + (f" ({', '.join(extra)})" if extra else "")
