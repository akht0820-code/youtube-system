$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c "C:\Users\user\Desktop\youtube-system\run.bat"'
$trigger = New-ScheduledTaskTrigger -Daily -At '10:00'
$settings = New-ScheduledTaskSettingsSet -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 3) -StartWhenAvailable
Register-ScheduledTask -TaskName 'YukkuriYouTubeDaily' -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force

Write-Host ''
Write-Host '=== 登録完了 ==='
Write-Host 'タスク名: YukkuriYouTubeDaily'
Write-Host '実行時刻: 毎日 10:00'
