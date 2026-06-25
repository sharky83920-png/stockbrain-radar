@echo off
chcp 65001 >nul
REM Launch StockBrain Dashboard (Streamlit) - desktop shortcut target
REM Runs in the user's own console so it stays up until this window is closed.
cd /d "%~dp0"
echo Starting StockBrain Dashboard... a browser will open at http://localhost:8501
echo (Keep this window open. Close it to stop the dashboard.)
".venv\Scripts\streamlit.exe" run "src\app\dashboard.py"
