@echo off
REM Claude Watchdog runner - called by Windows Task Scheduler every 1 minute
REM DRY_RUN mode: set CLAUDE_WATCHDOG_DRY_RUN=1 here to disable Discord notifications

cd /d C:\Users\user\Desktop\youtube-system

REM Phase 1b: notifications enabled. Set CLAUDE_WATCHDOG_DRY_RUN=1 to revert to dry-run mode.

C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe scripts\claude_watchdog.py >> logs\claude_watchdog_stdout.log 2>&1
exit /b %errorLevel%
