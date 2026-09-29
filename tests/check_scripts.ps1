$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$scripts = Get-ChildItem -LiteralPath $Root -Filter *.ps1
foreach ($script in $scripts) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
}

. (Join-Path $Root "update_common.ps1")
function Test-ExitCode { param([int]$Code) $global:LASTEXITCODE = $Code }
Invoke-Checked "successful command" Test-ExitCode 0
$caught = $false
try { Invoke-Checked "failed command" Test-ExitCode 7 }
catch {
    if ($_.Exception.Message -ne "failed command failed with exit code 7") { throw }
    $caught = $true
}
if (-not $caught) { throw "A failed command must stop the update pipeline." }
$global:LASTEXITCODE = 0
Write-Host "Parsed $($scripts.Count) scripts; command failure propagation passed."
