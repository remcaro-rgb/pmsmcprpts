# Change when the nightly FNS import runs (FNS_SYNC_TIME, hotel time) and restart fns-sync to use it.
# Windows (PowerShell) version of scripts/set_sync_time.sh.
#
# Usage (from the repository folder):
#   .\scripts\set_sync_time.ps1               # 03:30
#   .\scripts\set_sync_time.ps1 -Time 04:15
#
# Restarting doesn't import again if today's import already ran; it only moves the next one.
# If Windows blocks the script: powershell -ExecutionPolicy Bypass -File .\scripts\set_sync_time.ps1
param([string]$Time = "03:30")
$ErrorActionPreference = "Stop"

function Fail($message) { Write-Host "error: $message" -ForegroundColor Red; exit 1 }

$envFile = ".env"
if ($Time -notmatch '^([01]?[0-9]|2[0-3]):[0-5][0-9]$') { Fail "the time must look like 03:30 (it is '$Time')" }
if (-not (Test-Path $envFile)) { Fail "no $envFile here: run this from the repository folder" }

$lines = @(Get-Content $envFile)
if ($lines -match '^FNS_SYNC_TIME=') {
    $lines = $lines -replace '^FNS_SYNC_TIME=.*', "FNS_SYNC_TIME=$Time"
} else {
    $lines += "", "FNS_SYNC_TIME=$Time"
}
# UTF-8 without a BOM, which Docker Compose reads cleanly.
[System.IO.File]::WriteAllLines((Resolve-Path $envFile), [string[]]$lines)
Write-Host "FNS_SYNC_TIME=$Time in $envFile"

# Recreate the service so it reads the new value (a plain restart keeps the old environment).
docker compose --profile fns up -d fns-sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Start-Sleep -Seconds 5
docker compose logs --tail 20 fns-sync | Select-String "next import at" | Select-Object -Last 1
