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

    def real_by_file(self) -> dict[str, bool]:
        """File name -> whether it has any source=real row (for the data-role check)."""
        out: dict[str, bool] = {Path(f).name: False for f in self.files}
        for seg in self.segments:
            out[seg.file] = out.get(seg.file, False) or any(r.source == "real" for r in seg.rows)
        return out

    def relabelled(self, change: dict[int, str]) -> "Dataset":
        """A copy where the rows at the given positions (index into self.rows) get a new label."""
        segments, i = [], 0
        for seg in self.segments:
            rows = []
            for r in seg.rows:
                rows.append(r.with_meta(label=change[i]) if i in change else r)
                i += 1
            segments.append(Segment(seg.file, rows))
        return Dataset(self.files, segments, self.bad_rows)


HOLDOUT = "holdout"    # label given to held-out normal rows in the training copy (never trained on)


def holdout_last_normal(data: Dataset, frac: float) -> tuple[Dataset, Dataset, dict]:
    """Time split for validation: the LAST `frac` of the label=normal rows (in recording
    order, by ts_iso) are held out.

    Returns (train, validation, info):
      train       held-out normal rows relabelled "holdout" (skipped by training, and they
                  break the window, so no training window touches them)
      validation  the training normal rows relabelled "unknown" (not counted, but kept in
                  the stream so the live pipeline's windows run as they would live);
                  fault rows keep their label: the model never trains on them anyway
    """
    if not 0 < frac < 1:
        raise ValueError("holdout fraction must be between 0 and 1")
    rows = data.rows
    normal = sorted((i for i, r in enumerate(rows) if r.label == "normal"), key=lambda i: (rows[i].ts_iso, i))
    n_hold = int(round(len(normal) * frac))
    held = set(normal[len(normal) - n_hold:])
    kept = [i for i in normal if i not in held]
    info = {"holdout_frac": frac, "train_normal_rows": len(kept), "holdout_normal_rows": len(held),
            "holdout_from": rows[min(held, key=lambda i: (rows[i].ts_iso, i))].ts_iso if held else None}
    train = data.relabelled({i: HOLDOUT for i in held})
    validation = data.relabelled({i: "unknown" for i in kept})
    return train, validation, info


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
