@echo off
rem Build the portable app: release\MachineHealthMonitor\ and release\MachineHealthMonitor-v<version>-win64.zip
rem Needs (on the BUILD laptop only): Node.js 20+ and backend\venv (see backend\README.md).
rem Steps: dashboard build -> backend tests -> PyInstaller (onedir) -> assemble release folder -> zip.
setlocal
cd /d "%~dp0"
set "PY=%~dp0backend\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo ERROR: backend\venv not found. Create it first: cd backend ^&^& python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
  exit /b 1
)
where npm >nul 2>nul || (echo ERROR: npm not found. Install Node.js 20+ to build the dashboard. & exit /b 1)

echo.
echo === 1/5 Dashboard: npm ci + npm run build ===
pushd dashboard
call npm ci || (popd & echo ERROR: npm ci failed & exit /b 1)
call npm test || (popd & echo ERROR: dashboard tests failed & exit /b 1)
call npm run build || (popd & echo ERROR: dashboard build failed & exit /b 1)
popd

echo.
echo === 2/5 Backend tests ===
pushd backend
"%PY%" -m pytest -q || (popd & echo ERROR: backend tests failed & exit /b 1)
popd

echo.
echo === 3/5 PyInstaller (pinned in backend\requirements-build.txt) ===
"%PY%" -m pip install -q -r backend\requirements-build.txt || (echo ERROR: pip install failed & exit /b 1)
"%PY%" packaging\build_release.py version || exit /b 1
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN packaging\MachineHealthMonitor.spec --distpath backend\build\dist --workpath backend\build\work || (echo ERROR: PyInstaller failed & exit /b 1)

echo.
echo === 4/5 + 5/5 Assemble release\MachineHealthMonitor\ and zip ===
"%PY%" packaging\build_release.py assemble || (echo ERROR: assembling the release failed & exit /b 1)

echo.
echo Done. Copy release\MachineHealthMonitor\ (or the zip) to any Windows 10/11 laptop and run Start.bat.
endlocal
