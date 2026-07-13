@echo off
echo [SYSTEM] Initiating APEX Unified Launcher...
where uv >nul 2>&1
if errorlevel 1 (
  echo [SYSTEM] uv not found on PATH. Install uv before launching APEX.
  pause
  exit /b 1
)

uv run python launcher.py
set "exit_code=%ERRORLEVEL%"
pause
exit /b %exit_code%
