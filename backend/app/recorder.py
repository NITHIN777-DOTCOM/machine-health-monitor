"""Records rows to data/recordings/session_YYYYMMDD_HHMMSS.csv in the stored column order.

Every row is flushed (and fsynced) immediately, so a crash or power cut loses at most
the row being written.
"""
from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from .models import LABELS, TS_COLUMN, SensorRow, csv_header
from .registry import TIME_COLUMN, Registry

log = logging.getLogger(__name__)


class Recorder:
    def __init__(self, registry: Registry, recordings_dir: Path):
        self.registry = registry
        self.dir = recordings_dir
        self.path: Path | None = None
        self.rows_written = 0
        self.started_at: str | None = None
        self.label: str | None = None  # manual label for live rows; None = keep the row's own label
        self._file: IO[str] | None = None
        self._writer: Any = None

    @property
    def active(self) -> bool:
        return self._file is not None

    def start(self) -> Path:
        if self.active:
            assert self.path is not None
            return self.path
        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.dir / f"session_{stamp}.csv"
        n = 2
        while path.exists():
            path = self.dir / f"session_{stamp}_{n}.csv"
            n += 1
        self._file = path.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file, lineterminator="\n")
        self._writer.writerow(csv_header(self.registry))
        self._flush()
        self.path = path
        self.rows_written = 0
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        log.info("Recording started: %s", path)
        return path

    def stop(self) -> dict[str, Any]:
        started_at = self.started_at
        if self._file is not None:
            self._file.close()
            log.info("Recording stopped: %s (%d rows)", self.path, self.rows_written)
        self._file = None
        self._writer = None
        return {**self.status(), "started_at": started_at}

    def set_label(self, label: str | None) -> None:
        if label is not None and label not in LABELS:
            raise ValueError(f"label must be one of {LABELS} or null")
        self.label = label

    def write(self, row: SensorRow) -> None:
        if self._writer is None:
            return
        self._writer.writerow(row.to_csv_row(self.registry))
        self._flush()
        self.rows_written += 1

    def _flush(self) -> None:
        assert self._file is not None
        self._file.flush()
        os.fsync(self._file.fileno())

    def status(self) -> dict[str, Any]:
        return {
            "on": self.active,
            "file": self.path.name if self.path else None,
            "rows": self.rows_written,
            "started_at": self.started_at if self.active else None,
            "label": self.label,
        }


def list_recordings(recordings_dir: Path) -> list[dict[str, Any]]:
    """Name, size, row count, duration and last-modified time of every CSV in recordings_dir
    (newest first)."""
    out = []
    for path in sorted(recordings_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = path.stat()
        info: dict[str, Any] = {"file": path.name, "size_bytes": st.st_size, "rows": 0, "duration_s": None,
                                "modified": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds"),
                                "error": None}
        try:
            with path.open(newline="", encoding="utf-8") as f:
                first = last = None
                for record in csv.DictReader(line for line in f if not line.startswith("#")):
                    first = first or record
                    last = record
                    info["rows"] += 1
            if first and last:
                info["duration_s"] = _duration(first, last)
        except (OSError, csv.Error, UnicodeDecodeError) as exc:
            info["error"] = str(exc)
        out.append(info)
    return out


def _duration(first: dict[str, str], last: dict[str, str]) -> float | None:
    """Device-clock length (what a 1x replay takes; a 5x simulated recording is 5x longer
    than its wall-clock time), else wall-clock ts_iso if ms is missing or went backwards."""
    try:
        ms = (float(last[TIME_COLUMN]) - float(first[TIME_COLUMN])) / 1000.0
        if ms >= 0:
            return round(ms, 1)
    except (KeyError, TypeError, ValueError):
        pass
    try:
        delta = datetime.fromisoformat(last[TS_COLUMN]) - datetime.fromisoformat(first[TS_COLUMN])
        return round(delta.total_seconds(), 1)
    except (KeyError, TypeError, ValueError):
        return None
