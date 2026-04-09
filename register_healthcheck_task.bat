@echo off
REM YukkuriHealthCheck Task Scheduler Registration
REM Usage: Right-click this file -> "Run as administrator"

echo ============================================
echo  YukkuriHealthCheck Task Registration
echo ============================================
echo.

net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [ERROR] Administrator privileges required.
    echo Right-click this file and select "Run as administrator".
    echo.
    pause
    exit /b 1
)

if not exist "C:\Users\user\Desktop\youtube-system\run_healthcheck.bat" (
    echo [ERROR] run_healthcheck.bat not found
    pause
    exit /b 1
)
echo [OK] run_healthcheck.bat found
echo.

echo [RUN] schtasks /create ...
schtasks /create /tn "YukkuriHealthCheck" /tr "C:\Users\user\Desktop\youtube-system\run_healthcheck.bat" /sc daily /st 09:55 /rl HIGHEST /f
set RC=%errorLevel%
echo.

if %RC% == 0 (
    echo ============================================
    echo  SUCCESS: Registration complete
    echo ============================================
    echo.
    schtasks /query /tn YukkuriHealthCheck /fo LIST
) else (
    echo ============================================
    echo  FAILED: exit code %RC%
    echo ============================================
)

echo.
pause
