@echo off
title CryptoInfo Trading Bot Launcher

:: ────────────────────────────────────────────────────────────────────────────
:: run.bat  –  CryptoInfo Trading Bot Launcher (Windows)
:: Double-click this file to open the bot launcher with a graphical interface.
:: ────────────────────────────────────────────────────────────────────────────

echo.
echo  ===================================================
echo   CryptoInfo Trading Bot Launcher
echo  ===================================================
echo.

:: Change to the directory containing this script
cd /d "%~dp0"

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python is not installed or not in your PATH.
    echo.
    echo  Please install Python 3.9+ from:
    echo    https://www.python.org/downloads/
    echo.
    echo  During installation, make sure to tick:
    echo    [x] Add Python to PATH
    echo.
    pause
    exit /b 1
)

:: Run the launcher GUI
python launcher.py

if %errorlevel% neq 0 (
    echo.
    echo  The launcher exited with an error (code %errorlevel%).
    echo  See the output above for details.
    echo.
    pause
)
