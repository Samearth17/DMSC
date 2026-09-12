@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe goto missing
call .venv\Scripts\activate.bat
python -m app.cli serve --open
pause
exit /b
:missing
echo Run install_windows.bat first. Python 3.11 or newer is required.
pause
exit /b 1
