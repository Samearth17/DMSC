@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto missing
call .venv\Scripts\activate.bat
watchtower run --config config.yaml
set "WATCHTOWER_EXIT_CODE=%ERRORLEVEL%"
echo Exit status: %WATCHTOWER_EXIT_CODE%. 0=complete, 2=partial/failed/disabled audit.
pause
exit /b %WATCHTOWER_EXIT_CODE%
:missing
echo Run install_windows.bat first.
pause
exit /b 1
