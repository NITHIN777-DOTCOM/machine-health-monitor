@echo off
rem Demo backup: simulator only. Never opens a COM port, even with the Arduino plugged in.
rem Use this when the Arduino misbehaves or another program (Arduino IDE) holds the port.
title Machine Health Monitor (simulator only)
cd /d "%~dp0"
"%~dp0MachineHealthMonitor.exe" --simulator %*
if errorlevel 1 pause
