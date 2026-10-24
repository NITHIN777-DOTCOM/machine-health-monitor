"""PyInstaller entry point for MachineHealthMonitor.exe (see packaging/MachineHealthMonitor.spec).
The launcher itself is app/launcher.py; this stub exists because the entry script runs as
__main__, where the app package's relative imports would not work."""
import multiprocessing

from app.launcher import run

if __name__ == "__main__":
    multiprocessing.freeze_support()   # joblib/loky may start worker processes in the exe
    run()
