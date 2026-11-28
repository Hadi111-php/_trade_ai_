@echo off
REM ─────────────────────────────────────────────────────────────────────
REM  Futures MTF Lab — اجرای سریع روی ویندوز (PAPER فقط)
REM  استفاده:  run-mtf.bat selftest
REM             run-mtf.bat compare
REM             run-mtf.bat serve
REM ─────────────────────────────────────────────────────────────────────
setlocal
cd /d "%~dp0"

if "%1"=="selftest" goto selftest
if "%1"=="compare"  goto compare
if "%1"=="serve"    goto serve
if "%1"=="validate" goto validate
goto help

:selftest
python -m mtflab selftest
goto end

:compare
python -m mtflab compare --csv "..\futures-scalp-lab\data\btcusdt_1h_lastyear.csv" --out "results\dash_scenarios.html"
echo.
echo داشبورد ساخته شد: results\dash_scenarios.html
goto end

:serve
python -m mtflab serve --dir results --port 8080
goto end

:validate
python -m mtflab validate --data bybit --symbol BTCUSDT --tf-trigger 15m --tf-filter 1h --tf-bias 4h
goto end

:help
echo.
echo  Futures MTF Lab — راهنما
echo  ────────────────────────────────────────────
echo   run-mtf.bat selftest    خودآزمایی (تست‌ها + ضد lookahead)
echo   run-mtf.bat compare     مقایسهٔ سناریوی قدیم و جدید + داشبورد
echo   run-mtf.bat serve       سرو داشبورد روی http://localhost:8080
echo   run-mtf.bat validate    اعتبارسنجی کامل روی دادهٔ 15m (نیاز به اینترنت)
echo.
echo   برای دیدن همهٔ گزینه‌ها:  python -m mtflab --help
echo.
goto end

:end
endlocal
