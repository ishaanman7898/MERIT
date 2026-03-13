@echo off
title Gold Signal Bot - Setup
color 0A

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Python not found.
    echo.
    echo  1. Go to https://www.python.org/downloads/
    echo  2. Download and run the installer
    echo  3. IMPORTANT: tick "Add Python to PATH"
    echo  4. Re-run this file
    echo.
    pause
    exit /b 1
)

python setup.py
pause
