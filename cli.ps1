[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8NoBom
[Console]::InputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$repoRoot = $PSScriptRoot
. (Join-Path $repoRoot "scripts\tfi-runtime.ps1")

$runtime = Initialize-TfiRuntimeEnvironment -RepoRoot $repoRoot
$docker = Get-TfiDockerCommand

function Test-TfiWorkerRunning {
    param([string]$Docker)

    $args = Get-TfiComposeArguments -RepoRoot $repoRoot -Runtime $runtime -Arguments @("ps", "--status", "running", "--services")
    $result = Invoke-TfiHiddenProcess -FilePath $Docker -Arguments $args -SuppressOutput
    if ($result.ExitCode -ne 0) {
        return $false
    }
    $services = @($result.Stdout -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    return $services -contains "worker"
}

function Start-TfiWorker {
    param([string]$Docker)

    $args = Get-TfiComposeArguments -RepoRoot $repoRoot -Runtime $runtime -Arguments @("up", "-d", "--build")
    $result = Invoke-TfiHiddenProcess -FilePath $Docker -Arguments $args -SuppressOutput
    if ($result.ExitCode -eq 0) {
        return
    }

    if ($result.Stderr.Length -gt 0) { [Console]::Error.Write($result.Stderr) }
    if ($result.Stdout.Length -gt 0) { [Console]::Error.Write($result.Stdout) }
    throw "Failed to start TimelineForImage worker."
}

function Wait-TfiWorkerRunning {
    param(
        [string]$Docker,
        [int]$TimeoutSeconds = 30
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        if (Test-TfiWorkerRunning -Docker $Docker) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)

    return $false
}

if (-not (Test-TfiWorkerRunning -Docker $docker)) {
    Start-TfiWorker -Docker $docker
}

if (-not (Wait-TfiWorkerRunning -Docker $docker)) {
    throw "TimelineForImage worker did not reach the running state."
}

$execArgs = Get-TfiComposeArguments `
    -RepoRoot $repoRoot `
    -Runtime $runtime `
    -Arguments (@("exec", "-T") + (Get-TfiExecEnvironmentArguments) + @("worker", "python", "-m", "timeline_for_image_worker") + @($CliArgs))
$execResult = Invoke-TfiHiddenProcess -FilePath $docker -Arguments $execArgs -WriteOutput
exit $execResult.ExitCode
