@echo off
rem Run the backend test suite with a per-module coverage report.
rem Usage (from anywhere):  backend\scripts\run_tests.bat [extra pytest args]
cd /d "%~dp0.."
if not exist venv\Scripts\python.exe (
    echo venv not found. Create it first:  python -m venv venv  ^&^&  venv\Scripts\pip install -r requirements.txt
    exit /b 1
)
venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing %*
