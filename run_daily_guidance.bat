@echo off
REM Daily earnings-call (fashuo) guidance radar - called by Windows Task Scheduler
cd /d "C:\Users\user\projects\stockbrain-radar"
".venv\Scripts\python.exe" "scripts\daily_guidance.py" >> "data\daily_guidance.log" 2>&1
