@echo off
chcp 65001 >nul
title Scalp Lab - PAPER TRADE (risk engine)
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
%PY% -c "import scalplab" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] module scalplab peida nashod; in bat bayad DAKHEL apps\futures-scalp-lab bashad.
    pause
    exit /b 1
)

echo ==================================================================
echo   PAPER TRADE - risk engine ON, NO real orders   (Python: %PY%)
echo ==================================================================
%PY% -m scalplab auto --data binance --symbol BTCUSDT --tf 1m --interval 5 --forever ^
    --trade --size 100 --leverage 3 --max-concurrent 4 --cb-losses 2 ^
    --stop-pct 0.005 --trail-pct 0.003
echo.
echo Stopped. Press any key to close.
pause >nul
