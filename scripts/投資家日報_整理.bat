@echo off
chcp 65001 >nul
title 📡 StockBrain — 投資家日報整理

:: ── 路徑設定（跟著 repo 走，不需要改）──────────────────────────────
set REPO=%~dp0..
set PYTHON=%REPO%\.venv\Scripts\python.exe
set SCRIPT=%REPO%\scripts\read_investor_daily.py
set PENDING=G:\我的雲端硬碟\stockbrain\待閱讀區

:: ── 標題畫面 ──────────────────────────────────────────────────────
cls
echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║   📡  StockBrain — 投資家日報自動整理          ║
echo  ║                                              ║
echo  ║   流程：待閱讀區 PDF                          ║
echo  ║         → Gemini 萃取重點                    ║
echo  ║         → 知識庫/個股 寫入 MD                 ║
echo  ║         → 原始資料庫 封存 PDF                 ║
echo  ╚══════════════════════════════════════════════╝
echo.

:: ── 檢查 Python / venv ────────────────────────────────────────────
if not exist "%PYTHON%" (
    echo  ❌ 找不到 .venv，請先執行 setup_new_computer.bat
    echo.
    pause
    exit /b 1
)

:: ── 掃描待閱讀區，顯示 PDF 清單 ───────────────────────────────────
echo  📂 待閱讀區：%PENDING%
echo  ──────────────────────────────────────────────
set COUNT=0
for %%F in ("%PENDING%\*.pdf") do (
    set /a COUNT+=1
    echo    %%~nxF
)
if %COUNT%==0 (
    echo    （沒有 PDF，請先把日報 PDF 放進待閱讀區）
    echo.
    echo  💡 路徑：%PENDING%
    echo.
    pause
    exit /b 0
)
echo  ──────────────────────────────────────────────
echo  共 %COUNT% 份，即將開始整理 ...
echo.

:: ── 執行主腳本 ────────────────────────────────────────────────────
"%PYTHON%" -X utf8 "%SCRIPT%"
set EXIT=%errorlevel%

echo.
if %EXIT%==0 (
    echo  ✅ 整理完成！
    echo.
    echo  📁 MD 已存入：G:\我的雲端硬碟\stockbrain\知識庫\個股\
    echo  📦 PDF 已移至：G:\我的雲端硬碟\stockbrain\原始資料庫（原始格式）\投資家日報\
) else (
    echo  ❌ 執行過程有錯誤，請查看上方訊息。
)

echo.
pause
