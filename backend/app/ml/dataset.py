"""Load stored CSV recordings (DATA_CONTRACT.md section 5) into segments of rows.

A segment is a run of rows from one file with an increasing device clock; a device reset
(ms going backwards) starts a new segment, so windows never span two boot sessions.
"""
from __future__ import annotations

import csv
import glob
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ..models import SensorRow, row_from_stored
from ..registry import Registry

log = logging.getLogger(__name__)


@dataclass
class Segment:
    file: str
    rows: list[SensorRow] = field(default_factory=list)


@dataclass
class Dataset:
    files: list[str]
    segments: list[Segment]
    bad_rows: int = 0

    @property
    def rows(self) -> list[SensorRow]:
        return [r for s in self.segments for r in s.rows]

    def counts(self) -> dict[str, dict[str, int]]:
        """{"source": {...}, "label": {...}} over all rows."""
        rows = self.rows
        return {"source": dict(Counter(r.source for r in rows)), "label": dict(Counter(r.label for r in rows))}


def expand(patterns: Iterable[str]) -> list[Path]:
    """Files and globs -> sorted unique existing CSV paths."""
    out: dict[str, Path] = {}
    for pat in patterns:
        matches = glob.glob(pat) or ([pat] if Path(pat).is_file() else [])
        for m in matches:
            p = Path(m)
            if p.is_file():
                out[str(p.resolve())] = p
    return [out[k] for k in sorted(out)]


def load(patterns: Iterable[str], registry: Registry) -> Dataset:
    paths = expand(patterns)
    segments: list[Segment] = []
    bad = 0
    for path in paths:
        seg = Segment(path.name)
        with path.open(newline="", encoding="utf-8") as f:
            for record in csv.DictReader(line for line in f if not line.startswith("#")):
                try:
                    row = row_from_stored(record, registry)
                except ValueError:
                    bad += 1
                    continue
                if seg.rows and (row.ms is None or seg.rows[-1].ms is None or row.ms <= seg.rows[-1].ms):
                    segments.append(seg)
                    seg = Segment(path.name)
                seg.rows.append(row)
        if seg.rows:
            segments.append(seg)
    if bad:
        log.warning("Skipped %d malformed rows", bad)
    return Dataset([str(p) for p in paths], segments, bad)
