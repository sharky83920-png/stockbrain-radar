@echo off
REM 每日專家討論 - 由 Windows 工作排程器呼叫
cd /d "C:\Users\user\projects\stockbrain-radar"
".venv\Scripts\python.exe" "scripts\daily_debate.py" >> "data\daily_debate.log" 2>&1
