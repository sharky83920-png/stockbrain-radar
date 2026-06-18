@echo off
REM Telegram 雙向聽訊息 - 由 Windows 工作排程器每幾分鐘呼叫
cd /d "C:\Users\user\projects\stockbrain-radar"
".venv\Scripts\python.exe" "scripts\telegram_listener.py" >> "data\telegram_listener.log" 2>&1
