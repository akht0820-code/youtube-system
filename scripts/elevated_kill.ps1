# elevated_kill.ps1 — PIDファイルを読み取ってプロセスを強制終了する
# スケジュールタスク「YukkuriProcessKill」から管理者権限で実行される
# UAC確認なしで動作する

$pidFile = "C:\Users\user\Desktop\youtube-system\logs\kill_pids.txt"

if (-not (Test-Path $pidFile)) {
    exit 0
}

$pids = Get-Content $pidFile | Where-Object { $_ -match '^\d+$' }
foreach ($pid in $pids) {
    try {
        Stop-Process -Id $pid -Force -ErrorAction Stop
        Write-Output "Killed PID $pid"
    } catch {
        Write-Output "Failed PID $pid : $_"
    }
}

# 処理済みファイルを削除
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
