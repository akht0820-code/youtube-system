@echo off
chcp 65001 > nul
REM run_rebuild.bat — AquesTalk2音声再生成 + 動画再ビルド + YouTube予約投稿
REM 使い方: run_rebuild.bat <script_json> <audio_dir> [publish_at]

setlocal

set PYTHON=C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe
set SCRIPTS=%~dp0scripts

REM デフォルト引数（春バテ/自律神経テーマ）
set SCRIPT_JSON=%~dp0output\20260324_061600_春になるとだるい・眠い・イライラ…年度末ストレスが自律神経を.json
set AUDIO_DIR=%~dp0output\20260324_春になるとだるい・眠い・イライラ…年度末ストレスが自律神経を
set PUBLISH_AT=2026-03-24T18:00:00+09:00

echo ============================================================
echo  AquesTalk2 音声再生成 + いらすとや動画ビルド + YouTube投稿
echo ============================================================
echo  台本JSON: %SCRIPT_JSON%
echo  音声DIR: %AUDIO_DIR%
echo  予約公開: %PUBLISH_AT%
echo.

"%PYTHON%" "%SCRIPTS%\resynth_and_build.py" ^
    "%SCRIPT_JSON%" ^
    "%AUDIO_DIR%" ^
    --publish-at "%PUBLISH_AT%"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [エラー] 処理が失敗しました (code=%ERRORLEVEL%)
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo 全処理完了！
pause
