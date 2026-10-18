# Publish the local website (http://localhost:5050) on your free ngrok domain, behind a sign-in.
# Windows (PowerShell) version of scripts/share_ngrok.sh.
#
# One-time setup:
#   1. Sign up at https://ngrok.com and install ngrok (winget install ngrok.ngrok).
#   2. ngrok config add-authtoken <your token>        (from dashboard.ngrok.com -> Your Authtoken)
#   3. Copy your free domain from dashboard.ngrok.com -> Domains (e.g. something.ngrok-free.app).
#
# Usage (from the repository folder, with the stack running: docker compose up -d):
#   .\scripts\share_ngrok.ps1 -Domain something.ngrok-free.app -Google you@gmail.com
#   .\scripts\share_ngrok.ps1 -Domain something.ngrok-free.app -Google you@gmail.com,colleague@gmail.com
#   .\scripts\share_ngrok.ps1 -Domain something.ngrok-free.app -GoogleDomain yourcompany.com
#   .\scripts\share_ngrok.ps1 -Domain something.ngrok-free.app -Password admin:a-long-unique-password
#
# If Windows blocks the script: powershell -ExecutionPolicy Bypass -File .\scripts\share_ngrok.ps1 ...
# Press Ctrl+C to stop sharing.
param(
    [string]$Domain = $env:NGROK_DOMAIN,
    [string[]]$Google = @(),
    [string[]]$GoogleDomain = @(),
    [string]$Password = "",
    [int]$Port = $(if ($env:PMS_WEB_PORT) { [int]$env:PMS_WEB_PORT } else { 5050 }),
    [switch]$PublicNoSignIn  # anyone with the link can spend your Claude credits
)
$ErrorActionPreference = "Stop"

function Fail($message) { Write-Host "error: $message" -ForegroundColor Red; exit 1 }

if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Fail "ngrok is not installed: winget install ngrok.ngrok (or https://ngrok.com/download)"
}
ngrok config check *> $null
if ($LASTEXITCODE -ne 0) { Fail "ngrok is not set up: run 'ngrok config add-authtoken <your token>' (dashboard.ngrok.com -> Your Authtoken)" }

$Domain = ("$Domain" -replace '^https?://', '').TrimEnd('/')
if (-not $Domain) { Fail "pass -Domain with your free domain from dashboard.ngrok.com -> Domains (e.g. something.ngrok-free.app)" }

# Who may open the site. The website has no sign-in of its own unless WEB_AUTH=oidc is set.
$emails = @($Google | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$domains = @($GoogleDomain | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$authArgs = @()
if ($emails.Count -or $domains.Count) {
    $authArgs += @("--oauth", "google")
    foreach ($e in $emails) { $authArgs += @("--oauth-allow-email", $e) }
    foreach ($d in $domains) { $authArgs += @("--oauth-allow-domain", $d) }
}
if ($Password) {
    if ($authArgs.Count) { Fail "use either -Google/-GoogleDomain or -Password, not both" }
    $user, $pass = $Password -split ':', 2
    if (-not $user -or $null -eq $pass) { Fail "-Password must look like user:password" }
    if ($pass.Length -lt 12) { Fail "use a password of at least 12 characters" }
    $authArgs += @("--basic-auth", $Password)
}
if (-not $authArgs.Count -and -not $PublicNoSignIn) {
    Fail "add -Google you@gmail.com or -Password user:long-password, so strangers can't use your Claude credits"
}

# The site must be running locally.
try { Invoke-WebRequest -Uri "http://localhost:$Port/" -UseBasicParsing -TimeoutSec 5 | Out-Null }
catch { Fail "nothing answers on http://localhost:$Port; start it first: docker compose up -d" }

# Behind ngrok, rate limits should count per visitor (X-Forwarded-For), not per tunnel.
if (Test-Path .env) {
    $envText = Get-Content .env -Raw
    if ($envText -notmatch '(?m)^WEB_TRUST_PROXY=true\s*$') {
        Write-Host "Setting WEB_TRUST_PROXY=true in .env and restarting the website..."
        if ($envText -match '(?m)^WEB_TRUST_PROXY=') {
            $envText = $envText -replace '(?m)^WEB_TRUST_PROXY=.*$', 'WEB_TRUST_PROXY=true'
        } else {
            $envText = $envText.TrimEnd() + "`nWEB_TRUST_PROXY=true`n"
        }
        [System.IO.File]::WriteAllText((Join-Path (Get-Location) ".env"), $envText)
        docker compose up -d web | Out-Null
    }
}

# Newer ngrok agents take --url; older v3 agents take --domain.
$help = (ngrok http --help 2>&1) -join "`n"
$urlArgs = if ($help -match '--url') { @("--url", "https://$Domain") } else { @("--domain", $Domain) }

Write-Host ""
Write-Host "Sharing http://localhost:$Port at https://$Domain"
if (-not $authArgs.Count) {
    Write-Host "WARNING: no sign-in. Anyone with the link can use the site and your Claude credits." -ForegroundColor Yellow
} elseif ($Password) {
    Write-Host "Visitors sign in with the user name and password you chose."
} else {
    Write-Host "Visitors sign in with Google: $(($emails + ($domains | ForEach-Object { "anyone @$_" })) -join ', ')"
}
Write-Host "Free ngrok shows a warning page first; click 'Visit Site'. Press Ctrl+C to stop sharing."
Write-Host ""
& ngrok http $Port @urlArgs @authArgs
