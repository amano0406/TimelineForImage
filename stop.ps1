[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
docker compose --project-directory $repoRoot down
exit $LASTEXITCODE
