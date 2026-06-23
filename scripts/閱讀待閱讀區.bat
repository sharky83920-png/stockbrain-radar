@echo off
chcp 65001 >nul
title 📚 StockBrain — 統一閱讀器

set REPO=%~dp0..
set PYTHON=%REPO%\.venv\Scripts\python.exe
set PENDING=G:\我的雲端硬碟\stockbrain\待閱讀區

cls
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   📚  StockBrain 統一閱讀器                        ║
echo  ║                                                  ║
echo  ║   自動判斷 PDF 類型並分別整理：                      ║
echo  ║     📰 投資家日報  → 知識庫/個股/投資家日報           ║
echo  ║     📑 投顧報告    → 知識庫/個股/投顧報告             ║
echo  ║     ❓ 無法判斷    → 知識庫/個股/_未分類（人工確認）   ║
echo  ╚══════════════════════════════════════════════════╝
echo.

if not exist "%PYTHON%" (
    echo  ❌ 找不到 .venv，請先執行 setup_new_computer.bat
    pause & exit /b 1
)

echo  📂 待閱讀區：%PENDING%
echo  ──────────────────────────────────────────────────
set COUNT=0
for %%F in ("%PENDING%\*.pdf") do (
    set /a COUNT+=1
    echo    %%~nxF
)
if %COUNT%==0 (
    echo    （沒有 PDF）
    echo.
    echo  💡 把 PDF 放進待閱讀區後再執行：
    echo     %PENDING%
    echo.
    pause & exit /b 0
)
echo  ──────────────────────────────────────────────────
echo  共 %COUNT% 份，開始整理 ...
echo.

"%PYTHON%" -X utf8 "%REPO%\scripts\read_pending.py"

echo.
echo  ════════════════════════════════════════════════
echo  ✅ 整理完成！
echo.
echo  📁 MD 存入位置：
echo     G:\我的雲端硬碟\stockbrain\知識庫\個股\
echo  📦 原始 PDF 已移至：
echo     G:\我的雲端硬碟\stockbrain\原始資料庫（原始格式）\
echo  ════════════════════════════════════════════════
echo.
pause
