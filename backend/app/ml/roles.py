"""Data roles from data/recordings/MANIFEST.json (Phase 8.2), enforced in code.

Every real recording has a role:
  train  may be used for training, threshold tuning and validation
  test   held out: final evaluation only, never for training, tuning or choosing anything
A "raw" variant (the same session with its live labels, data/recordings/raw/) has its
session's role. Files are matched by name and by content hash (line endings normalised,
so a git checkout with CRLF still matches), so a renamed copy of the test session is
still recognised as the test session.

Who checks what:
  scripts/train.py, generate_synthetic.py --from-real   strict: every file with real rows
                                                        must be a listed "train" session
  POST /api/model/train (jobs.py)                       not strict: "test" files are refused,
                                                        unlisted recordings (a deployed
                                                        machine's own data) are allowed
  scripts/evaluate.py                                   final test: "train" files refused;
                                                        --validation: only "train" files
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..paths import MANIFEST_FILE

log = logging.getLogger(__name__)

TRAIN, TEST = "train", "test"


class RoleError(Exception):
    pass


@dataclass(frozen=True)
class FileRole:
    file: str          # the manifest's name for it (relative to data/recordings)
    session: str       # the session's main (cleaned) file
    role: str
    variant: str       # "cleaned" or "raw"


def content_hash(path: Path) -> str:
    """sha256 of the file with CRLF normalised to LF."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class Manifest:
    def __init__(self, data: dict | None = None, path: Path | None = None):
        self.path = path
        self.entries: list[FileRole] = []
        self._by_name: dict[str, FileRole] = {}
        self._by_hash: dict[str, FileRole] = {}
        for s in (data or {}).get("sessions", []):
            variants = [(s, "cleaned")] + [(r, "raw") for r in s.get("raw", [])]
            for entry, variant in variants:
                fr = FileRole(entry["file"], s["file"], s["role"], variant)
                self.entries.append(fr)
                self._by_name[Path(entry["file"]).name] = fr
                if entry.get("sha256"):
                    self._by_hash[entry["sha256"]] = fr

    @classmethod
    def load(cls, path: Path = MANIFEST_FILE) -> "Manifest":
        """A missing manifest means no roles are known (e.g. the portable app)."""
        try:
            return cls(json.loads(Path(path).read_text(encoding="utf-8")), Path(path))
        except FileNotFoundError:
            return cls(None, None)

    def lookup(self, path: Path) -> FileRole | None:
        path = Path(path)
        by_name = self._by_name.get(path.name)
        if by_name is not None:
            return by_name
        if self._by_hash and path.is_file():
            return self._by_hash.get(content_hash(path))
        return None

    def role(self, path: Path) -> str | None:
        fr = self.lookup(path)
        return fr.role if fr else None


def _describe(path: Path, fr: FileRole) -> str:
    alias = "" if Path(path).name == Path(fr.file).name else f" (same content as {fr.file})"
    return f"{Path(path).name}{alias}: session {fr.session}, role '{fr.role}'"


def check_training(files: Iterable[Path], has_real: dict[str, bool], manifest: Manifest,
                   *, strict: bool = True) -> list[str]:
    """Raise RoleError if a file may not be used for training. has_real maps a file name to
    whether it contains source=real rows (synthetic-only files need no role).
    Returns notes for the user."""
    notes, refused = [], []
    for path in files:
        path = Path(path)
        fr = manifest.lookup(path)
        if fr is not None and fr.role != TRAIN:
            refused.append(f"{_describe(path, fr)}: held out, never used for training")
        elif fr is None and has_real.get(path.name, False):
            if strict:
                refused.append(f"{path.name}: real recording not listed in MANIFEST.json "
                               "(add it with role 'train' or 'test' first)")
            else:
                notes.append(f"{path.name}: not in MANIFEST.json, used as the machine's own recording")
        elif fr is not None:
            notes.append(f"{_describe(path, fr)}")
    if refused:
        raise RoleError("Training refused by the data roles (data/recordings/MANIFEST.json):\n  "
                        + "\n  ".join(refused))
    return notes


def check_evaluation(files: Iterable[Path], manifest: Manifest, *, validation: bool = False) -> list[str]:
    """Final test (default): any 'train' file is refused, its numbers would be optimistic.
    Validation: only 'train' files; the test session must not influence any choice."""
    notes, refused = [], []
    for path in files:
        path = Path(path)
        fr = manifest.lookup(path)
        if validation:
            if fr is None or fr.role != TRAIN:
                what = _describe(path, fr) if fr else f"{path.name}: not in MANIFEST.json"
                refused.append(f"{what}: validation uses 'train' sessions only")
            else:
                notes.append(f"VALIDATION on a training session: {_describe(path, fr)}")
        elif fr is not None and fr.role == TRAIN:
            refused.append(f"{_describe(path, fr)}: a training session cannot give final test numbers "
                           "(use --validation for validation checks)")
        elif fr is not None:
            notes.append(f"held-out test data: {_describe(path, fr)}")
        else:
            notes.append(f"{path.name}: not in MANIFEST.json (no role known)")
    if refused:
        raise RoleError("Evaluation refused by the data roles (data/recordings/MANIFEST.json):\n  "
                        + "\n  ".join(refused))
    return notes
