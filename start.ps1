[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
if (-not $env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT) {
    $env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT = "C:\"
}

$docker = "docker"
Write-Host "Starting TimelineForImage worker..."
& $docker compose --project-directory $repoRoot up -d --build worker
if (-not $?) {
    throw "docker compose failed."
}

Write-Host ""
Write-Host "TimelineForImage worker is running."
Write-Host ""
Write-Host "CLI examples:"
Write-Host "  .\cli.ps1 settings init"
Write-Host "  .\cli.ps1 settings status"
Write-Host "  .\cli.ps1 files list"
Write-Host "  .\cli.ps1 items refresh --max-items 4"
Write-Host "  .\cli.ps1 items list"
Write-Host "  .\cli.ps1 runs list"
Write-Host ""
& $docker compose --project-directory $repoRoot ps
exit $LASTEXITCODE
