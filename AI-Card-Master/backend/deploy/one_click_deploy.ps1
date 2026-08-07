# One-click deploy wrapper for Windows operator laptops (plan §40).
# Prefer running the real deploy on the Linux origin host via SSH;
# this script is for dry-run / inventory checks from the repo checkout.
#
# Usage (from backend/):
#   powershell -File deploy/one_click_deploy.ps1 -DryRun -Profile production
#   powershell -File deploy/one_click_deploy.ps1 -PrintInventory

param(
    [string]$Profile = "production",
    [string]$Restore = "",
    [switch]$DryRun,
    [switch]$PrintInventory,
    [switch]$SkipEnvCheck
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$argsList = @("deploy/one_click_deploy.py", "--profile", $Profile)
if ($DryRun) { $argsList += "--dry-run" }
if ($PrintInventory) { $argsList += "--print-inventory" }
if ($SkipEnvCheck) { $argsList += "--skip-env-check" }
if ($Restore -ne "") { $argsList += @("--restore", $Restore) }

python @argsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
