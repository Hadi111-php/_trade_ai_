@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Adding Scalp Lab AUTO to Windows startup (PAPER only)...
powershell -NoProfile -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Startup'),'ScalpLab-AUTO.lnk')); $s.TargetPath='%~dp0start-auto.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo Done. It will start automatically on Windows login.
echo To remove, run disable-autostart.bat
pause
