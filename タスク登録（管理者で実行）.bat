@echo off
chcp 65001 > nul

echo タスクスケジューラに登録します...

set TASK_NAME=YukkuriYouTubeDaily
set BAT_PATH=C:\Users\user\Desktop\youtube-system\run.bat
set LOG_DIR=C:\Users\user\Desktop\youtube-system\logs

REM ログディレクトリを作成
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM 既存タスクを削除
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

REM タスクを登録（毎日10:00、最高権限で実行）
schtasks /create /tn "%TASK_NAME%" /tr "cmd.exe /c \"%BAT_PATH%\"" /sc DAILY /st 10:00 /rl HIGHEST /f

if %errorlevel% == 0 (
    echo.
    echo ===========================
    echo  登録完了！
    echo  タスク名: %TASK_NAME%
    echo  毎日10:00に自動実行
    echo  YouTube公開: 18:00予約
    echo ===========================
) else (
    echo.
    echo [エラー] 管理者権限で実行してください
    echo このファイルを右クリック → 管理者として実行
)

echo.
pause
