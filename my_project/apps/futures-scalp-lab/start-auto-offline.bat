@echo off
chcp 65001 >nul
title Futures Scalp Lab - AUTO (offline test)
cd /d "%~dp0"

set PY=python
where python >nul 2>nul || set PY=py

echo ============================================================
echo   Offline test - synthetic data, 500 ticks, PAPER only
echo ============================================================
%PY% -m scalplab auto --data synthetic --max-ticks 500 --seed 7
echo.
echo Done. Press any key to close.
pause >nul
