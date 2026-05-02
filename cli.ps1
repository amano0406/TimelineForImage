[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
if (-not $env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT) {
    $env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT = "C:\"
}

$docker = "docker"
& $docker compose --project-directory $repoRoot up -d --build worker
if (-not $?) {
    throw "Failed to start TimelineForImage worker."
}

& $docker compose --project-directory $repoRoot exec -T worker python -m timeline_for_image_worker @CliArgs
exit $LASTEXITCODE
