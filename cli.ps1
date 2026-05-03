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

$docker = "docker.exe"

$previousErrorActionPreference = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    & $docker compose --project-directory $repoRoot build worker *> $null
    $buildExitCodeVariable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    $buildExitCode = if ($null -eq $buildExitCodeVariable) { 0 } else { [int]$buildExitCodeVariable.Value }
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

if ($buildExitCode -ne 0) {
    throw "Failed to build TimelineForImage worker."
}

try {
    $ErrorActionPreference = "Continue"
    & $docker compose --project-directory $repoRoot run --rm --no-deps worker @CliArgs
    $runExitCodeVariable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
    $runExitCode = if ($null -eq $runExitCodeVariable) { 0 } else { [int]$runExitCodeVariable.Value }
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
}

exit $runExitCode
