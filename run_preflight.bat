@echo off
cd /d C:\Users\user\Desktop\youtube-system\scripts
set PYTHON=C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe
set LOG=C:\Users\user\Desktop\youtube-system\logs\preflight.log

echo [%date% %time%] === PREFLIGHT START === >> %LOG%

REM --- 1st check: verify + resume if needed ---
%PYTHON% -X utf8 -u preflight_check.py >> %LOG% 2>&1
set EC=%ERRORLEVEL%
if %EC% == 0 goto :done

REM --- exit=1: クラッシュまたは検証エラー → 生成しない（通知済み） ---
if %EC% == 1 (
    echo [%date% %time%] === ERROR exit=1 - 生成は実行しない === >> %LOG%
    goto :done
)

REM --- exit=2: パイプラインなし → 新規生成 ---
if %EC% == 2 (
    echo [%date% %time%] === NO PIPELINE - full generation === >> %LOG%
    %PYTHON% -X utf8 -u generator.py --auto --publish-time 18:00 >> %LOG% 2>&1

    echo [%date% %time%] === POST-GENERATION RECHECK === >> %LOG%
    %PYTHON% -X utf8 -u preflight_check.py >> %LOG% 2>&1
    if %ERRORLEVEL% == 0 goto :done

    echo [%date% %time%] === FULL GENERATION ALSO FAILED === >> %LOG%
    goto :done
)

REM --- exit=3: リジューム失敗 → 新規生成はしない（2026-04-09事故対策） ---
REM   既存runの再開が失敗した状態で新規生成を走らせると、
REM   全く無関係な動画が予約投稿される危険がある。
REM   preflight_check.py 側で既に高優先度通知を出しているため、ここでは何もしない。
if %EC% == 3 (
    echo [%date% %time%] === RESUME FAILED - NOT running full generation (safety) === >> %LOG%
    goto :done
)

REM --- 想定外のexit code → 安全側（生成しない） ---
echo [%date% %time%] === UNKNOWN EXIT CODE %EC% - 生成は実行しない === >> %LOG%

:done
echo [%date% %time%] === PREFLIGHT END === >> %LOG%
exit /b 0
