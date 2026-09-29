$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartScript = Join-Path $Root "start_local_site.ps1"
$TaskName = "StockScoreTerminal-LocalServer"
$Description = "Start Stock Score Terminal local web server on user logon."

if (-not (Test-Path $StartScript)) {
    throw "Start script not found: $StartScript"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$StartScript`"" `
    -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description $Description `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Registered and started task: $TaskName"
