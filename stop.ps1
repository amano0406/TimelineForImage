[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$docker = "docker.exe"
& $docker compose --project-directory $repoRoot down
$exitCodeVariable = Get-Variable -Name LASTEXITCODE -Scope Global -ErrorAction SilentlyContinue
if ($null -eq $exitCodeVariable) {
    exit 0
}
exit $global:LASTEXITCODE
