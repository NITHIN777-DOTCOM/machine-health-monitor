"""Background training jobs for POST /api/model/train (one-click retraining, Phase 8).

Runs the same code as scripts/train.py in a worker thread, saves to models/, then calls
on_done() so the backend reloads the new model without a restart. One job at a time.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..config import Settings
from ..registry import Registry
from ..sources.replay import resolve_recording
from . import dataset, training

log = logging.getLogger(__name__)


class JobBusy(Exception):
    pass


class TrainJobs:
    def __init__(self, registry: Registry, settings: Settings, on_done: Callable[[], Awaitable[None]]):
        self.registry = registry
        self.settings = settings
        self.on_done = on_done
        self.jobs: dict[str, dict[str, Any]] = {}
        self._task: asyncio.Task[None] | None = None

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, files: list[str]) -> dict[str, Any]:
        """Validate and launch. Raises ValueError, FileNotFoundError or JobBusy."""
        if not files:
            raise ValueError("give at least one recording file name (from GET /api/recordings)")
        if self.busy:
            raise JobBusy("a training job is already running")
        paths = [resolve_recording(self.settings.recordings_dir, f) for f in files]
        job = {"id": uuid.uuid4().hex[:8], "status": "queued", "step": "queued", "files": list(files),
               "started": time.time(), "finished": None, "elapsed_s": 0.0, "message": None, "result": None}
        self.jobs[job["id"]] = job
        self._task = asyncio.create_task(self._run(job, paths), name=f"train-{job['id']}")
        return self.view(job["id"])

    def view(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        end = job["finished"] or time.time()
        return {**job, "elapsed_s": round(end - job["started"], 1)}

    async def _run(self, job: dict[str, Any], paths: list[Path]) -> None:
        s = self.settings
        try:
            job.update(status="running", step="loading recordings")
            data = await asyncio.to_thread(dataset.load, [str(p) for p in paths], self.registry)
            job["step"] = "training"
            model, meta = await asyncio.to_thread(
                training.train, data, self.registry, window_s=s.ml_window_s, max_missing_frac=s.ml_max_missing_frac)
            job["step"] = "saving"
            await asyncio.to_thread(training.save, model, meta, s.models_dir)
            job["step"] = "reloading model"
            await self.on_done()
            t = meta["training"]
            job.update(status="done", step="done", message="model trained and reloaded",
                       result={"windows": t["windows"], "rows_normal_by_source": t["rows_normal_by_source"],
                               "provisional": meta["provisional"], "created": meta["created"]})
            log.info("Training job %s done: %s", job["id"], job["result"])
        except training.TrainingError as exc:
            job.update(status="failed", message=str(exc))
        except asyncio.CancelledError:
            job.update(status="failed", message="cancelled (server shutting down)")
            raise
        except Exception as exc:  # noqa: BLE001 - report, never crash the server
            log.exception("Training job %s failed", job["id"])
            job.update(status="failed", message=f"{type(exc).__name__}: {exc}")
        finally:
            job["finished"] = time.time()

    async def shutdown(self) -> None:
        if self.busy:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
