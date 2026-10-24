"""Release helper for build.bat (run with backend\\venv\\Scripts\\python).

    python packaging/build_release.py version      # -> backend/build/version.json (bundled into the exe)
    python packaging/build_release.py assemble     # PyInstaller output -> release/MachineHealthMonitor/ + zip

assemble builds this folder (and zips it as release/MachineHealthMonitor-v<version>-win64.zip):

    MachineHealthMonitor/
      MachineHealthMonitor.exe, _internal/      the PyInstaller onedir build
      Start.bat, Start (simulator only).bat
      QUICK_START.txt
      config/        settings.json, sensors.json, sim_profile.json (editable)
      models/        model.joblib, model_meta.json (PROVISIONAL: simulated training data)
      data/recordings/   empty: new recordings go here
      data/demo/     demo_SIMULATED_drift_recovery.csv (simulated, for replay / warm start)
      firmware/      README.md and machine_monitor/ sources
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
PACKAGING = REPO / "packaging"
PYI_OUT = BACKEND / "build" / "dist" / "MachineHealthMonitor"
RELEASE = REPO / "release"
APP = RELEASE / "MachineHealthMonitor"

sys.path.insert(0, str(BACKEND))
from app.version import VERSION, git_describe  # noqa: E402


def write_version() -> None:
    info = {"version": VERSION, "git": git_describe(), "build_date": date.today().isoformat()}
    out = BACKEND / "build" / "version.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"version.json: {info}")


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


def assemble() -> int:
    if not (PYI_OUT / "MachineHealthMonitor.exe").is_file():
        print(f"ERROR: {PYI_OUT} has no MachineHealthMonitor.exe; run PyInstaller first", file=sys.stderr)
        return 1
    if APP.exists():
        shutil.rmtree(APP)
    shutil.copytree(PYI_OUT, APP)
    for name in ("Start.bat", "Start (simulator only).bat"):
        shutil.copy2(PACKAGING / name, APP / name)
    quick = (PACKAGING / "QUICK_START.txt").read_text(encoding="utf-8").replace("{version}", VERSION)
    (APP / "QUICK_START.txt").write_text(quick.replace("\n", "\r\n"), encoding="utf-8", newline="")

    (APP / "config").mkdir()
    for name in ("settings.json", "sensors.json", "sim_profile.json"):
        shutil.copy2(BACKEND / "config" / name, APP / "config" / name)
    (APP / "models").mkdir()
    for name in ("model.joblib", "model_meta.json", "README.md"):
        shutil.copy2(REPO / "models" / name, APP / "models" / name)
    rec = APP / "data" / "recordings"
    rec.mkdir(parents=True)
    (rec / "README.txt").write_text(
        "New recordings (Record button in the dashboard) are saved here as session_YYYYMMDD_HHMMSS.csv.\r\n",
        encoding="utf-8", newline="")
    demo = subprocess.run([sys.executable, str(BACKEND / "scripts" / "make_demo_recording.py"),
                           "--out", str(APP / "data" / "demo")], cwd=BACKEND)
    if demo.returncode != 0:
        return demo.returncode

    fw = APP / "firmware"
    shutil.copytree(REPO / "firmware" / "machine_monitor", fw / "machine_monitor",
                    ignore=shutil.ignore_patterns(".gitkeep"))
    shutil.copy2(REPO / "firmware" / "README.md", fw / "README.md")

    zip_path = RELEASE / f"MachineHealthMonitor-v{VERSION}-win64.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(APP.rglob("*")):
            arc = Path("MachineHealthMonitor") / p.relative_to(APP)
            if p.is_dir() and not any(p.iterdir()):
                z.writestr(str(arc).replace("\\", "/") + "/", "")     # keep empty folders
            elif p.is_file():
                z.write(p, arc)
    print(f"\nRelease folder: {APP}  ({_mb(_size(APP))}, {sum(1 for _ in APP.rglob('*'))} entries)")
    print(f"Zip:            {zip_path}  ({_mb(zip_path.stat().st_size)})")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "version":
        write_version()
        sys.exit(0)
    if cmd == "assemble":
        sys.exit(assemble())
    print(__doc__)
    sys.exit(2)
