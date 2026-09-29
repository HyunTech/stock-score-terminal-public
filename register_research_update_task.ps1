$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $Root "run_research_update_logged.ps1"
$TaskName = "StockScoreTerminal-ResearchUpdate"
$Description = "Collect and publish Korean securities research brief twice daily."

if (-not (Test-Path $RunScript)) {
    throw "Run script not found: $RunScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$RunScript`"" `
    -WorkingDirectory $Root

$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At 08:00),
    (New-ScheduledTaskTrigger -Daily -At 20:00)
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description $Description `
    -Force | Out-Null

Write-Host "Registered task: $TaskName"
Write-Host "Schedule: every day at 08:00 and 20:00 local time"
Write-Host "Run script: $RunScript"
