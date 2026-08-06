# Fast rollback to the previous container image (Windows helper for plan §24).
# Prefer bash deploy/rollback.sh on the Linux production host.
# Usage (from backend/):
#   powershell -File deploy/rollback.ps1
#   powershell -File deploy/rollback.ps1 -To previous
#   powershell -File deploy/rollback.ps1 -WithDbDowngrade -1

param(
    [string]$To = "previous",
    [string]$WithDbDowngrade = "",
    [string]$ImageName = $(if ($env:IMAGE_NAME) { $env:IMAGE_NAME } else { "ai-card-master-backend" }),
    [string]$HealthUrl = $(if ($env:HEALTH_URL) { $env:HEALTH_URL } else { "http://127.0.0.1/health/ready" }),
    [int]$ApiReplicas = $(if ($env:API_REPLICAS) { [int]$env:API_REPLICAS } else { 1 }),
    [int]$WorkerReplicas = $(if ($env:WORKER_REPLICAS) { [int]$env:WORKER_REPLICAS } else { 1 })
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$composeArgs = @("-f", "docker-compose.yml", "-f", "deploy/docker-compose.scale.yml")

docker image inspect "${ImageName}:${To}" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Rollback image missing: ${ImageName}:${To}"
}

Write-Host "==> Rolling back to ${ImageName}:${To}"

docker image inspect "${ImageName}:current" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    $failedTag = "failed-" + (Get-Date -Format "yyyyMMddTHHmmss")
    docker tag "${ImageName}:current" "${ImageName}:${failedTag}"
}

docker tag "${ImageName}:${To}" "${ImageName}:current"
$env:IMAGE_TAG = "current"

docker compose @composeArgs up -d --force-recreate `
    --scale "api=$ApiReplicas" `
    --scale "worker=$WorkerReplicas" `
    api worker beat nginx

if ($WithDbDowngrade -ne "") {
    Write-Host "==> Alembic downgrade $WithDbDowngrade"
    docker compose @composeArgs exec -T api alembic downgrade $WithDbDowngrade
}

$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3 | Out-Null
        $ok = $true
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $ok) {
    Write-Error "Rollback health check failed: $HealthUrl"
}

New-Item -ItemType Directory -Force -Path "deploy/releases" | Out-Null
$stamp = Get-Date -Format "yyyyMMddTHHmmss"
@{
    rolled_back_to = "${ImageName}:${To}"
    db_downgrade   = $(if ($WithDbDowngrade) { $WithDbDowngrade } else { $null })
    at_utc         = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json | Set-Content -Path "deploy/releases/rollback-$stamp.json"

Write-Host "==> Rollback OK"
