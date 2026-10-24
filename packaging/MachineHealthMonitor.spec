# PyInstaller spec for the portable app. Built by build.bat (repo root); by hand, from the repo root:
#   backend\venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\MachineHealthMonitor.spec
#       --distpath backend\build\dist --workpath backend\build\work
#
# ONEDIR, not onefile: the result is a folder (MachineHealthMonitor.exe + _internal\).
# A onefile exe unpacks ~150 MB into %TEMP% on every start (slow, worse from a pendrive) and
# that self-extracting pattern is what antivirus heuristics flag most often. See README.md.
#
# Bundled read-only resources (app/paths.py resolves them under sys._MEIPASS):
#   dashboard/dist/   the built dashboard (npm run build)
#   backend/config/   default settings.json, sensors.json, sim_profile.json
#   models/           the shipped model + meta
#   version.json      written by `packaging/build_release.py version`
import os
from PyInstaller.utils.hooks import collect_submodules

REPO = os.path.abspath(os.path.join(SPECPATH, ".."))
BACKEND = os.path.join(REPO, "backend")
VERSION_JSON = os.path.join(BACKEND, "build", "version.json")


def need(path):
    if not os.path.exists(path):
        raise SystemExit(f"missing {path}: run build.bat (it builds the dashboard and writes version.json first)")
    return path


datas = [
    (need(os.path.join(REPO, "dashboard", "dist")), "dashboard/dist"),
    (os.path.join(BACKEND, "config", "settings.json"), "backend/config"),
    (os.path.join(BACKEND, "config", "sensors.json"), "backend/config"),
    (os.path.join(BACKEND, "config", "sim_profile.json"), "backend/config"),
    (os.path.join(REPO, "models", "model.joblib"), "models"),
    (os.path.join(REPO, "models", "model_meta.json"), "models"),
    (need(VERSION_JSON), "."),
]

# Imported by name at runtime (string imports, protocol auto-selection, pickled model classes),
# so static analysis can miss them.
hiddenimports = (
    collect_submodules("app")
    + collect_submodules("uvicorn")            # uvicorn picks loops/protocols by string ("auto")
    + collect_submodules("websockets")         # uvicorn's WebSocket protocol for /ws/stream
    + collect_submodules("starlette")
    + collect_submodules("fastapi")
    + collect_submodules("serial.tools")       # pyserial list_ports_windows is chosen at import time
    + collect_submodules("sklearn.ensemble")   # the pickled IsolationForest and its trees
    + collect_submodules("sklearn.tree")
    + collect_submodules("sklearn.utils")
    + ["joblib", "numpy", "anyio._backends._asyncio", "h11", "httptools", "email.mime.text"]
)

# Not used at runtime (pandas: nothing in app/ imports it; sklearn treats it as optional).
# Excluding them keeps the folder smaller and the start faster.
excludes = ["tkinter", "matplotlib", "pandas", "pytest", "IPython", "notebook", "PIL", "pyarrow",
            "scipy.io.matlab.tests", "sklearn.datasets.tests"]

a = Analysis(
    [os.path.join(BACKEND, "mhm_entry.py")],
    pathex=[BACKEND],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,                     # onedir: binaries go into _internal\
    name="MachineHealthMonitor",
    console=True,                              # the console window shows the banner; closing it stops the app
    upx=False,                                 # UPX-packed exes trigger more antivirus false positives
    debug=False,
    strip=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="MachineHealthMonitor",
)
