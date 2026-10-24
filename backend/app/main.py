"""FastAPI app: REST API + WebSocket stream, and the built dashboard at "/".

Run from backend/:  uvicorn app.main:app --reload
The portable exe starts it through app/launcher.py.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import paths

from .analysis import compact
from .config import load_settings
from .ml.jobs import JobBusy
from .pipeline import Pipeline
from .recorder import Recorder, list_recordings
from .sources.replay import resolve_recording
from .registry import Registry
from .sources.serial_source import port_exists, resolve_port
from .state import AppState, RingBuffer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("mhm")


def _build_state() -> AppState:
    paths.ensure_app_dirs()
    settings = load_settings()
    registry = Registry.load()
    return AppState(
        registry=registry,
        settings=settings,
        recorder=Recorder(registry, settings.recordings_dir),
        history=RingBuffer(settings.history_seconds, settings.max_speed),
    )


def _choose_startup_source(state: AppState) -> tuple[str, str]:
    """Serial if the port picked by resolve_port() (MHM_PORT > auto > settings) exists.
    MHM_SOURCE=simulator skips the serial side entirely (no port is listed or opened)."""
    if state.settings.force_source == "simulator":
        return "simulator", "MHM_SOURCE=simulator; serial disabled, using simulator (normal)"
    port, how = resolve_port(state.settings)
    if port is None:
        return "simulator", "no Arduino found; using simulator (normal)"
    if how == "auto-detected" or port_exists(port):
        return "serial", f"Arduino on {port} ({how})"
    return "simulator", f"{port} ({how}) is not present; using simulator (normal)"


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = _build_state()
    pipeline = Pipeline(state)
    app.state.mhm = state
    app.state.pipeline = pipeline

    kind, reason = _choose_startup_source(state)
    state.startup_reason = reason
    log.info("Startup source: %s (%s)", kind, reason)
    warm = state.settings.warmstart_file
    if warm:
        try:
            resolve_recording(state.settings.recording_dirs, warm)
        except FileNotFoundError as exc:
            log.warning("warmstart_file %r not used: %s", warm, exc)
            warm = None
    await pipeline.switch(pipeline.make_source(kind), warmstart_file=warm)
    try:
        yield
    finally:
        await pipeline.shutdown()
        state.recorder.stop()


app = FastAPI(title="Predictive Machine Health Monitor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


def _state() -> AppState:
    return app.state.mhm


def _pipeline() -> Pipeline:
    return app.state.pipeline


# ---- request bodies ------------------------------------------------------------------

class SourceRequest(BaseModel):
    type: Literal["simulator", "serial", "replay"]
    scenario: str | None = None
    speed: float | None = None
    file: str | None = None
    loop: bool = False
    warmstart: str | None = None     # recording to warm-start the new source from


class LabelRequest(BaseModel):
    label: Literal["normal", "fault", "unknown"] | None


class FileRequest(BaseModel):
    file: str


class TrainRequest(BaseModel):
    files: list[str]


# ---- REST ----------------------------------------------------------------------------

@app.get("/api/status")
async def get_status():
    return _pipeline().status()


@app.get("/api/sensors")
async def get_sensors():
    return _state().registry.to_dict()


@app.get("/api/history")
async def get_history(seconds: float = Query(600, gt=0), detail: Literal["compact", "full", "none"] = "compact"):
    """Rows of the last N seconds, each with its analysis (compact: overall, ML status,
    health and forecast seconds, enough for trend charts; full: the whole analysis block)."""
    items = _state().history.since(seconds)
    rows = []
    for row, analysis in items:
        d = row.to_dict()
        if detail != "none":
            d["analysis"] = analysis if detail == "full" else compact(analysis)
        rows.append(d)
    return {"seconds": seconds, "count": len(rows), "rows": rows}


@app.post("/api/source")
async def set_source(req: SourceRequest):
    pipeline = _pipeline()
    try:
        if req.warmstart:
            resolve_recording(_state().settings.recording_dirs, req.warmstart)   # 404 before switching
        source = pipeline.make_source(req.type, scenario=req.scenario, speed=req.speed, file=req.file, loop=req.loop)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    try:
        await pipeline.switch(source, warmstart_file=req.warmstart)
    except ValueError as exc:                     # recording exists but has no usable rows
        raise HTTPException(400, str(exc))
    return pipeline.status()


@app.post("/api/record/start")
async def record_start():
    path = _state().recorder.start()
    await _pipeline().notify_status()
    return {"file": path.name, **_state().recorder.status()}


@app.post("/api/record/stop")
async def record_stop():
    summary = _state().recorder.stop()
    await _pipeline().notify_status()
    return summary


@app.post("/api/label")
async def set_label(req: LabelRequest):
    _state().recorder.set_label(req.label)
    await _pipeline().notify_status()
    return {"label": req.label}


@app.get("/api/recordings")
async def get_recordings():
    return {"recordings": list_recordings(_state().settings.recording_dirs)}


@app.post("/api/warmstart")
async def warmstart(req: FileRequest):
    try:
        n = _pipeline().warm_start(req.file)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await _pipeline().notify_status()
    return {"file": req.file, "rows": n, "message": f"warm-starting from {req.file} ({n} rows) at the next row"}


# ---- model -----------------------------------------------------------------------------

@app.get("/api/model")
async def get_model():
    return _pipeline().model_info()


@app.get("/api/model/evaluation")
async def get_model_evaluation():
    """Held-out test results of the model (rules vs ML), or {"available": false, "message": ...}."""
    return _pipeline().evaluation()


@app.post("/api/model/reload")
async def reload_model():
    return await _pipeline().reload_model()


@app.post("/api/model/train", status_code=202)
async def train_model(req: TrainRequest):
    try:
        return _pipeline().train_jobs.start(req.files)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except JobBusy as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/model/train/{job_id}")
async def train_status(job_id: str):
    job = _pipeline().train_jobs.view(job_id)
    if job is None:
        raise HTTPException(404, f"no training job {job_id!r}")
    return job


# ---- WebSocket -----------------------------------------------------------------------

@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    broadcaster = _state().broadcaster
    broadcaster.clients.add(ws)
    try:
        await ws.send_json({"type": "status", "status": _pipeline().status()})
        while True:
            await ws.receive_text()  # we don't expect messages; this just detects disconnects
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.clients.discard(ws)


# ---- the dashboard (dashboard/dist, built with `npm run build`) ------------------------
# Registered last, so every /api and /ws route above wins. Any other path serves a file
# from dist, or index.html (single-page app fallback). In development the Vite dev server
# (http://127.0.0.1:5173) still works as before and proxies to the API.

NOT_BUILT = ("The dashboard is not built. Run `npm run build` in dashboard/, or use the Vite dev "
             "server: `npm run dev` in dashboard/, then open http://127.0.0.1:5173")


@app.get("/{path:path}", include_in_schema=False)
async def dashboard(path: str):
    if path.split("/", 1)[0] in ("api", "ws"):
        raise HTTPException(404, f"no endpoint /{path}")
    dist = paths.DASHBOARD_DIR.resolve()
    index = dist / "index.html"
    if not index.is_file():
        return PlainTextResponse(NOT_BUILT, status_code=503)
    target = (dist / path).resolve()
    if path and target.is_file() and target.is_relative_to(dist):
        return FileResponse(target)
    if "." in path.rsplit("/", 1)[-1]:          # a missing file (e.g. an old asset name): 404, not the page
        raise HTTPException(404, f"no file /{path}")
    # index.html must not be cached: after an update the browser fetches the new asset names.
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
