@echo off
REM Auto stock event radar called by Windows Task Scheduler
REM Pulls TWSE OpenAPI and writes the auto events json into the vault
cd /d "C:\Users\user\projects\stockbrain-radar"
".venv\Scripts\python.exe" "scripts\auto_events.py" >> "data\auto_events.log" 2>&1
