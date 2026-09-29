$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root "logs"
$UpdateScript = Join-Path $Root "update_research.ps1"

if (-not (Test-Path $UpdateScript)) {
    throw "Update script not found: $UpdateScript"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogPath = Join-Path $LogDir "research-update-$timestamp.log"
$LatestLogPath = Join-Path $LogDir "research-update-latest.log"

function Write-Log {
    param([Parameter(Mandatory = $true)][string]$Message)
    $Message | Tee-Object -FilePath $LogPath -Append
}

try {
    Write-Log "Research update started: $(Get-Date -Format o)"
    Write-Log "Workspace: $Root"
    Set-Location $Root
    $StdoutPath = Join-Path $LogDir "research-update-$timestamp.stdout.tmp"
    $StderrPath = Join-Path $LogDir "research-update-$timestamp.stderr.tmp"
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$UpdateScript`"" `
        -WorkingDirectory $Root `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath
    if (Test-Path $StdoutPath) {
        Get-Content -Path $StdoutPath | Add-Content -Path $LogPath
        Remove-Item -LiteralPath $StdoutPath -Force
    }
    if (Test-Path $StderrPath) {
        Get-Content -Path $StderrPath | Add-Content -Path $LogPath
        Remove-Item -LiteralPath $StderrPath -Force
    }
    $exitCode = $process.ExitCode
    Write-Log "Research update finished: $(Get-Date -Format o) exitCode=$exitCode"
    exit $exitCode
}
catch {
    Write-Log "Research update failed: $($_.Exception.Message)"
    exit 1
}
finally {
    Copy-Item -LiteralPath $LogPath -Destination $LatestLogPath -Force
}
