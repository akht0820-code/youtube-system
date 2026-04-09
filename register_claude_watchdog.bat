@echo off
REM Register ClaudeWatchdog task in Windows Task Scheduler
REM Usage: Right-click -> "Run as administrator"
REM Uses XML definition for MultipleInstancesPolicy=IgnoreNew and precise settings
REM v2.3: pythonw.exe 直接起動、3分周期、コンソール窓なし

echo ============================================
echo  ClaudeWatchdog Task Registration (v2.3)
echo ============================================
echo.

net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [ERROR] Administrator privileges required.
    echo Right-click this file and select "Run as administrator".
    pause
    exit /b 1
)

if not exist "C:\Users\user\AppData\Local\Programs\Python\Python311\pythonw.exe" (
    echo [ERROR] pythonw.exe not found at expected path
    pause
    exit /b 1
)
echo [OK] pythonw.exe found

if not exist "C:\Users\user\Desktop\youtube-system\scripts\claude_watchdog.py" (
    echo [ERROR] claude_watchdog.py not found
    pause
    exit /b 1
)
echo [OK] claude_watchdog.py found

if not exist "C:\Users\user\Desktop\youtube-system\scripts\claude_watchdog_task.xml" (
    echo [ERROR] claude_watchdog_task.xml not found
    pause
    exit /b 1
)
echo [OK] claude_watchdog_task.xml found
echo.

echo [RUN] schtasks /create /xml ...
schtasks /create /tn "ClaudeWatchdog" /xml "C:\Users\user\Desktop\youtube-system\scripts\claude_watchdog_task.xml" /f
set RC=%errorLevel%
echo.

if %RC% == 0 (
    echo ============================================
    echo  SUCCESS: Registration complete
    echo ============================================
    echo.
    schtasks /query /tn ClaudeWatchdog /fo LIST
) else (
    echo ============================================
    echo  FAILED: exit code %RC%
    echo ============================================
)

echo.
pause
