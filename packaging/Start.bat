@echo off
rem Predictive Machine Health Monitor: uses the Arduino if one is plugged in, else the simulator.
rem Opens the dashboard in your browser. Close this window to stop.
title Machine Health Monitor
cd /d "%~dp0"
"%~dp0MachineHealthMonitor.exe" %*
if errorlevel 1 pause
