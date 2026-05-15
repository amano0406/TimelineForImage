[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\tfi-runtime.ps1")

$runtime = Initialize-TfiRuntimeEnvironment -RepoRoot $repoRoot -NoPersist
$docker = Get-TfiDockerCommand

Write-Host "Stopping TimelineForImage worker..."
Write-Host "Instance: $($runtime.InstanceName)"

$downArgs = Get-TfiComposeArguments -RepoRoot $repoRoot -Runtime $runtime -Arguments @("down")
$stopResult = Invoke-TfiHiddenProcess -FilePath $docker -Arguments $downArgs -WriteOutput
exit $stopResult.ExitCode
