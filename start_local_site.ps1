$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$SiteDir = Join-Path $Root "site"
$LogDir = Join-Path $Root "logs"
$Port = 8002

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $message = "$(Get-Date -Format s) stock score site already listening on http://127.0.0.1:$Port/"
    Add-Content -Path (Join-Path $LogDir "local-site-startup.log") -Value $message
    Write-Host $message
    exit 0
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $pyLauncher = (Get-Command py -ErrorAction SilentlyContinue).Source
    if (-not $pyLauncher) {
        throw "Python was not found in PATH. Install Python or add it to PATH before startup."
    }
    $python = $pyLauncher
    $arguments = "-3 -m http.server $Port --bind 127.0.0.1 --directory `"$SiteDir`""
} else {
    $arguments = "-m http.server $Port --bind 127.0.0.1 --directory `"$SiteDir`""
}

$stdout = Join-Path $LogDir "local-site.stdout.log"
$stderr = Join-Path $LogDir "local-site.stderr.log"
Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr

$message = "$(Get-Date -Format s) started stock score site at http://127.0.0.1:$Port/"
Add-Content -Path (Join-Path $LogDir "local-site-startup.log") -Value $message
Write-Host $message
