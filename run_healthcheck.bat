@echo off
setlocal enabledelayedexpansion
cd /d C:\Users\user\Desktop\youtube-system\scripts
set PYTHON=C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe
set LOG=C:\Users\user\Desktop\youtube-system\logs\preflight_runtime.log

echo [!date! !time!] === HEALTHCHECK START === >> %LOG%
%PYTHON% -X utf8 -u preflight_runtime.py >> %LOG% 2>&1
set HC_EXIT=!ERRORLEVEL!
echo [!date! !time!] === HEALTHCHECK END (exit=!HC_EXIT!) === >> %LOG%
endlocal & exit /b %HC_EXIT%
