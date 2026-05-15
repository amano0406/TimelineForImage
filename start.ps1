[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\tfi-runtime.ps1")

$runtime = Initialize-TfiRuntimeEnvironment -RepoRoot $repoRoot
$docker = Get-TfiDockerCommand

Write-Host "Starting TimelineForImage runtime..."
Write-Host "Instance: $($runtime.InstanceName)"
Write-Host "Local health URL: $($runtime.ApiBaseUrl)/health"

$startArgs = Get-TfiComposeArguments -RepoRoot $repoRoot -Runtime $runtime -Arguments @("up", "-d", "--build")
$startResult = Invoke-TfiHiddenProcess -FilePath $docker -Arguments $startArgs -WriteOutput
if ($startResult.ExitCode -ne 0) {
    throw "docker compose failed."
}

Write-Host ""
Write-Host "TimelineForImage runtime is running."
Write-Host "Image processing does not start automatically; run .\cli.ps1 items refresh when needed."
Write-Host ""
Write-Host "CLI examples:"
Write-Host "  .\cli.ps1 settings init"
Write-Host "  .\cli.ps1 settings status"
Write-Host "  .\cli.ps1 files list"
Write-Host "  .\cli.ps1 items refresh --max-items 4"
Write-Host "  .\cli.ps1 items list"
Write-Host "  .\cli.ps1 runs list"
Write-Host "  .\cli.ps1 health"
Write-Host "  .\cli.ps1 maintenance cleanup --dry-run"
Write-Host ""
Write-Host "Health API:"
Write-Host "  curl.exe $($runtime.ApiBaseUrl)/health"
Write-Host ""

$psArgs = Get-TfiComposeArguments -RepoRoot $repoRoot -Runtime $runtime -Arguments @("ps")
$psResult = Invoke-TfiHiddenProcess -FilePath $docker -Arguments $psArgs -WriteOutput
exit $psResult.ExitCode
