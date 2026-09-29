$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $Root "run_daily_update_logged.ps1"
$TaskName = "StockScoreTerminal-DailyUpdate"
$Description = "Update Korean stock data, scores, GitHub, and Netlify after Korean market close."

if (-not (Test-Path $RunScript)) {
    throw "Run script not found: $RunScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`"" `
    -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 18:30
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description $Description `
    -Force | Out-Null

Write-Host "Registered task: $TaskName"
Write-Host "Schedule: weekdays at 18:30 local time"
Write-Host "Run script: $RunScript"
