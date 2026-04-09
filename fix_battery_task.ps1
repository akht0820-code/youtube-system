$task = Get-ScheduledTask -TaskName "YukkuriYouTubeDaily"
$settings = $task.Settings
$settings.DisallowStartIfOnBatteries = $false
$settings.StopIfGoingOnBatteries = $false
Set-ScheduledTask -TaskName "YukkuriYouTubeDaily" -Settings $settings
Write-Host "完了: バッテリー制限を解除しました"
