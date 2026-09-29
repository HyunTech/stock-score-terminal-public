$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PYTHONUTF8 = "1"
. (Join-Path $Root "update_common.ps1")

Invoke-Checked "Collecting Telegram research..." python .\collect_telegram.py --timeout 2
Invoke-Checked "Collecting configured securities reports..." python .\collect_reports.py
Invoke-Checked "Collecting Naver Finance research reports..." python .\collect_naver_reports.py
Invoke-Checked "Analyzing research brief..." python .\analyze_research.py
Invoke-Checked "Checking frontend script syntax..." node --check .\site\app.js

Write-Host "Local analysis saved to local-output. No Git push or deployment is performed."
