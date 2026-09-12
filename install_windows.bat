@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto fail
call .venv\Scripts\activate.bat
python -m pip install -e ".[all]"
if errorlevel 1 goto fail
if not exist config.yaml copy config\config.example.yaml config.yaml
echo Installation complete. Run start_dashboard.bat to configure and run audits in your browser.
pause
exit /b 0
:fail
echo Installation failed. Ensure Python 3.11 or newer and internet access are available.
pause
exit /b 1
