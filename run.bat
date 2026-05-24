@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo.
    echo --------------------------------------------------------
    echo JobHunt exited with code %errorlevel%
    echo Log file: %APPDATA%\JobHunt\jobhunt.log
    echo --------------------------------------------------------
    pause
)
