@echo off
chcp 65001 >nul
title Futures Scalp Lab - AUTO (PAPER)
cd /d "%~dp0"

:: --- پیدا کردن پایتون ---
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY ( where python3 >nul 2>nul && set PY=python3 )
if not defined PY (
    echo [ERROR] Python peida nashod. Python 3.9+ nasb kon va "Add to PATH" ra bezan.
    pause
    exit /b 1
)

:: --- بررسی ماژول ---
%PY% -c "import scalplab" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] module scalplab peida nashod.
    echo motmaen sho in bat DAKHEL pushay apps\futures-scalp-lab ejra mishavad.
    pause
    exit /b 1
)

echo ============================================================
echo   Futures Scalp Lab - AUTO   [PAPER only - NO real orders]
echo   Python: %PY%
echo ============================================================
%PY% -m scalplab auto --data binance --symbol BTCUSDT --tf 1m --interval 5 --forever
echo.
echo Lab stopped. Press any key to close.
pause >nul
