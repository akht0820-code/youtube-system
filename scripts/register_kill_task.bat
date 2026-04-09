@echo off
schtasks /create /tn "YukkuriProcessKill" /tr "powershell.exe -ExecutionPolicy Bypass -File C:\Users\user\Desktop\youtube-system\scripts\elevated_kill.ps1" /sc once /st 00:00 /rl highest /f
echo %ERRORLEVEL%
pause
