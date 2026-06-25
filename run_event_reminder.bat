@echo off
chcp 65001 >nul
REM Event reminder (Telegram) - called daily by Windows Task Scheduler
cd /d "%~dp0"
".venv\Scripts\python.exe" "scripts\event_reminder.py" >> "data\event_reminder.log" 2>&1
