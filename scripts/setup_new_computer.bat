@echo off
chcp 65001 >nul
title 📡 StockBrain — 新電腦安裝

cls
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   📡  StockBrain Radar — 新電腦安裝精靈           ║
echo  ╚══════════════════════════════════════════════════╝
echo.
echo  此腳本會自動完成：
echo    1. 確認 Python 3.10+
echo    2. 建立 .venv 虛擬環境
echo    3. 安裝所有套件（requirements.txt）
echo    4. 建立 .env 設定檔（填入 API Key）
echo    5. 建立桌面捷徑
echo.
pause

:: ── Step 1: 確認 Python ───────────────────────────────────────────
echo.
echo  [1/5] 確認 Python 版本 ...
python --version 2>nul
if errorlevel 1 (
    echo  ❌ 找不到 Python！
    echo.
    echo  請先安裝 Python 3.10+：
    echo  https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)
echo  ✅ Python OK

:: ── Step 2: 建立 .venv ────────────────────────────────────────────
echo.
echo  [2/5] 建立虛擬環境 .venv ...
set REPO=%~dp0..
if exist "%REPO%\.venv" (
    echo  ✅ .venv 已存在，略過建立
) else (
    python -m venv "%REPO%\.venv"
    echo  ✅ .venv 建立完成
)

:: ── Step 3: 安裝套件 ──────────────────────────────────────────────
echo.
echo  [3/5] 安裝套件（可能需要 2~5 分鐘）...
"%REPO%\.venv\Scripts\pip" install -r "%REPO%\requirements.txt" --quiet
if errorlevel 1 (
    echo  ❌ 套件安裝失敗，請查看上方錯誤訊息
    pause
    exit /b 1
)
echo  ✅ 套件安裝完成

:: ── Step 4: 建立 .env ────────────────────────────────────────────
echo.
echo  [4/5] 設定 API Key ...
set ENV_FILE=%REPO%\.env

if exist "%ENV_FILE%" (
    echo  ✅ .env 已存在，確認 GEMINI_KEY 是否填寫 ...
    findstr "GEMINI_KEY=AIza" "%ENV_FILE%" >nul 2>&1
    if errorlevel 1 (
        echo  ⚠️  GEMINI_KEY 可能未填寫，請開啟 .env 確認：
        echo     %ENV_FILE%
    ) else (
        echo  ✅ GEMINI_KEY 已設定
    )
) else (
    echo  建立 .env 範本 ...
    (
        echo GEMINI_KEY=請貼上你的_Gemini_API_Key
        echo GEMINI_MODEL=gemini-2.0-flash-lite
        echo FINMIND_TOKEN=
        echo RADAR_VAULT_DIR=G:\我的雲端硬碟\stockbrain
        echo RADAR_WATCHLIST_PATH=G:\我的雲端硬碟\stockbrain\工具欄\radar_watchlist.json
        echo STOCKBRAIN_KB_DIR=G:\我的雲端硬碟\stockbrain\知識庫
    ) > "%ENV_FILE%"
    echo.
    echo  ⚠️  請開啟以下檔案，填入你的 Gemini API Key：
    echo     %ENV_FILE%
    echo.
    echo  Gemini API Key 取得：https://aistudio.google.com/apikey
    echo.
    notepad "%ENV_FILE%"
    echo  填完存檔後，按 Enter 繼續 ...
    pause >nul
)

:: ── Step 5: 建立桌面捷徑 ──────────────────────────────────────────
echo.
echo  [5/5] 建立桌面捷徑 ...
powershell -ExecutionPolicy Bypass -File "%REPO%\scripts\建立桌面捷徑.ps1" -RepoPath "%REPO%"

:: ── 完成 ──────────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   🎉  安裝完成！                                  ║
echo  ║                                                  ║
echo  ║   每日使用方式：                                   ║
echo  ║     1. 把日報 PDF 丟進 待閱讀區                    ║
echo  ║     2. 雙擊桌面「📡 投資家日報整理」                ║
echo  ║     3. 完成 ✅                                    ║
echo  ║                                                  ║
echo  ║   啟動 Dashboard：                                ║
echo  ║     雙擊 scripts\啟動Dashboard.bat（如有）         ║
echo  ╚══════════════════════════════════════════════════╝
echo.
pause
