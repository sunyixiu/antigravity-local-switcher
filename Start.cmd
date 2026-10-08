@echo off
where pythonw.exe >nul 2>nul
if errorlevel 1 (
  echo Python with tkinter is required. No packages need to be installed.
  pause
  exit /b 1
)
start "" pythonw.exe "%~dp0local_switcher.py"
