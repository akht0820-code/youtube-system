@echo off
setlocal enabledelayedexpansion
cd /d C:\Users\user\Desktop\youtube-system\scripts
set PYTHON=C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe
set LOG=C:\Users\user\Desktop\youtube-system\logs\run.log
set WSL_DISTRO=Ubuntu
set WSL_USER=aki
set RESULT=0

echo [!date! !time!] === BATCH START === >> %LOG%

REM --- Network connectivity check (max 5min, 30s interval x 10) ---
echo [!date! !time!] Checking network... >> %LOG%
set NET_OK=0
for /L %%i in (1,1,10) do (
    if !NET_OK! == 0 (
        %PYTHON% -X utf8 network_check.py >> %LOG% 2>&1
        if !ERRORLEVEL! == 0 (
            set NET_OK=1
        ) else (
            echo [!date! !time!] Network check %%i/10 failed, waiting 30s... >> %LOG%
            timeout /t 30 /nobreak > nul
        )
    )
)
if !NET_OK! == 0 (
    echo [!date! !time!] === NETWORK UNAVAILABLE after 5min - ABORT === >> %LOG%
    %PYTHON% -X utf8 -c "from notifier import notify_error; notify_error('network_check', RuntimeError('Network check 10/10 failed - ABORT'))" >> %LOG% 2>&1
    set RESULT=2
    goto :post_run
)
echo [!date! !time!] Network OK >> %LOG%

REM --- 1st attempt ---
%PYTHON% -X utf8 -u generator.py --auto --publish-time 18:00 >> %LOG% 2>&1
if !ERRORLEVEL! == 0 goto :post_run

echo [!date! !time!] === 1st attempt FAILED (exit=!ERRORLEVEL!) - retry in 10min === >> %LOG%
timeout /t 600 /nobreak > nul

REM --- 2nd attempt (resume from failed phase) ---
%PYTHON% -X utf8 -u generator.py --auto --publish-time 18:00 --resume >> %LOG% 2>&1
if !ERRORLEVEL! == 0 goto :post_run

echo [!date! !time!] === 2nd attempt FAILED (exit=!ERRORLEVEL!) - retry in 10min === >> %LOG%
timeout /t 600 /nobreak > nul

REM --- 3rd attempt (resume from failed phase) ---
%PYTHON% -X utf8 -u generator.py --auto --publish-time 18:00 --resume >> %LOG% 2>&1
if !ERRORLEVEL! == 0 goto :post_run

echo [!date! !time!] === ALL 3 ATTEMPTS FAILED === >> %LOG%
set RESULT=1

:post_run
REM Post-run monitoring (always runs regardless of success/failure)
%PYTHON% -X utf8 -u run_monitor.py >> %LOG% 2>&1

REM Auto-regenerate CLAUDE_PROJECT_CONTEXT.md (WSL-hosted memory access)
REM -d/-u を固定しないと既定 distro/user 変更時に memory パスが解決できなくなる
REM wsl.exe 起動失敗（distro 不一致/python3 不在等）時はスマホ通知を飛ばす
REM （Python 内の失敗は build_project_context.py 側で notify_failure 済み）
wsl.exe -d %WSL_DISTRO% -u %WSL_USER% bash -lc "cd /mnt/c/Users/user/Desktop/youtube-system && python3 scripts/build_project_context.py" >> %LOG% 2>&1
if errorlevel 1 (
    set WSL_CTX_EXIT=!ERRORLEVEL!
    echo [!date! !time!] build_project_context.py failed inside WSL exit=!WSL_CTX_EXIT! >> %LOG%
    %PYTHON% -X utf8 -c "from notifier import notify_error; notify_error('build_project_context_wsl', RuntimeError('wsl.exe exit=!WSL_CTX_EXIT! distro=%WSL_DISTRO% user=%WSL_USER%'))" >> %LOG% 2>&1
)

echo [!date! !time!] === BATCH END (exit=!RESULT!) === >> %LOG%
endlocal & exit /b %RESULT%
