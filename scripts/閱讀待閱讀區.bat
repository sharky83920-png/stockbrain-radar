@echo off
chcp 65001 >nul
title StockBrain Reader

set REPO=%~dp0..
set PYTHON=%REPO%\.venv\Scripts\python.exe

if not exist "%PYTHON%" (
    echo [ERROR] .venv not found - run setup_new_computer.bat first
    pause & exit /b 1
)

"%PYTHON%" -X utf8 "%REPO%\scripts\read_pending.py"

echo.
pause
