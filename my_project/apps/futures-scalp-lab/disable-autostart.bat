@echo off
chcp 65001 >nul
echo Removing Scalp Lab AUTO from Windows startup...
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ScalpLab-AUTO.lnk" 2>nul
powershell -NoProfile -Command "Remove-Item ([IO.Path]::Combine([Environment]::GetFolderPath('Startup'),'ScalpLab-AUTO.lnk')) -ErrorAction SilentlyContinue"
echo Done. Autostart disabled.
pause
