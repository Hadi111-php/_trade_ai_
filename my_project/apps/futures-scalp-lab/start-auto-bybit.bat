@echo off
chcp 65001 >nul
title Futures Scalp Lab - BYBIT AUTO (PAPER)
cd /d "%~dp0"

set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY ( where python3 >nul 2>nul && set PY=python3 )
if not defined PY (
    echo [ERROR] Python peida nashod. Python 3.9+ nasb kon va "Add to PATH" ra bezan.
    pause
    exit /b 1
)

echo ============================================================
echo   Futures Scalp Lab - BYBIT AUTO   [PAPER only]
echo   Symbol: BTCUSDT | Timeframe: 1m | Interval: 5s
echo ============================================================
%PY% -m scalplab auto --data bybit --symbol BTCUSDT --tf 1m --interval 5 --forever
echo.
echo Lab stopped. Press any key to close.
pause >nul
