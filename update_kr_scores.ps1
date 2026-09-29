$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:PYTHONUTF8 = "1"
. (Join-Path $Root "update_common.ps1")

function Get-UpdatedRowCount {
    $LogPath = Join-Path $Root "data\metadata\kr_incremental_update_log.csv"
    if (-not (Test-Path $LogPath)) {
        return 0
    }
    $rows = Import-Csv $LogPath
    return ($rows | Where-Object { $_.status -like "updated*" } | Measure-Object).Count
}

Invoke-Checked "Updating Korean daily OHLCV data..." python .\update_kr_incremental.py --source pykrx --fallback-source pykrx --max-failure-rate 0.02 --sleep 0.02

$updatedFiles = Get-UpdatedRowCount
if ($updatedFiles -eq 0) {
    Write-Host "No Korean OHLCV files changed. Continuing with score rebuild."
}

Invoke-Checked "Fetching DART disclosures for BCI..." python .\fetch_disclosures.py --days 14 --max-pages 20
Invoke-Checked "Fetching Naver news for BCI..." python .\fetch_news.py --limit 300 --display 10 --sleep 0.1
Invoke-Checked "Recomputing scores..." python .\score_universe.py

Write-Host "Local analysis saved to local-output. No Git push or deployment is performed."
