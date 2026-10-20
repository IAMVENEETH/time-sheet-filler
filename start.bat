@echo off
rem Double-click to open Timesheet Filler (Windows).
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
uv run --quiet python app.py
if errorlevel 1 pause
