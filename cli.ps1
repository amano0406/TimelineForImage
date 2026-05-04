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
if (-not $env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT) {
    $env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT = "C:\"
}

$forwardedEnvironmentNames = @(
    "TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT",
    "TIMELINE_FOR_IMAGE_SETTINGS_PATH",
    "TIMELINE_FOR_IMAGE_SETTINGS_EXAMPLE_PATH",
    "TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT",
    "TIMELINE_FOR_IMAGE_WORKER_INTERVAL_SECONDS"
)

function Format-TfiProcessArgument {
    param([string]$Value)

    if ($null -eq $Value) { return '""' }
    $text = [string]$Value
    if ($text.Length -eq 0) { return '""' }
    if ($text -notmatch '[\s"]') { return $text }

    $builder = [System.Text.StringBuilder]::new()
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $text.ToCharArray()) {
        if ($character -eq '\') { $backslashes += 1; continue }
        if ($character -eq '"') {
            if ($backslashes -gt 0) { [void]$builder.Append(('\' * ($backslashes * 2))); $backslashes = 0 }
            [void]$builder.Append('\"')
            continue
        }
        if ($backslashes -gt 0) { [void]$builder.Append(('\' * $backslashes)); $backslashes = 0 }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) { [void]$builder.Append(('\' * ($backslashes * 2))) }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Invoke-TfiHiddenProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [switch]$WriteOutput,
        [switch]$SuppressOutput
    )

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (@($Arguments) | ForEach-Object { Format-TfiProcessArgument -Value ([string]$_) }) -join " "
    $startInfo.WorkingDirectory = $repoRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $startInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $fileDirectory = Split-Path -Parent $FilePath
    if ($fileDirectory) {
        $currentPath = $startInfo.EnvironmentVariables["PATH"]
        if (-not $currentPath) {
            $currentPath = $env:PATH
        }
        $updatedPath = "$fileDirectory;$currentPath"
        $startInfo.EnvironmentVariables["PATH"] = $updatedPath
        $startInfo.EnvironmentVariables["Path"] = $updatedPath
    }
    $startInfo.EnvironmentVariables["PATHEXT"] = ".COM;.EXE;.BAT;.CMD;.VBS;.VBE;.JS;.JSE;.WSF;.WSH;.MSC;.CPL"
    foreach ($name in $script:forwardedEnvironmentNames) {
        $value = [System.Environment]::GetEnvironmentVariable($name, "Process")
        if ($null -ne $value) {
            $startInfo.EnvironmentVariables[$name] = $value
        }
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()

    $stdout = [string]$stdoutTask.Result
    $stderr = [string]$stderrTask.Result
    if ($WriteOutput -and -not $SuppressOutput) {
        if ($stdout.Length -gt 0) { [Console]::Out.Write($stdout) }
        if ($stderr.Length -gt 0) { [Console]::Error.Write($stderr) }
    }

    return [pscustomobject]@{
        ExitCode = [int]$process.ExitCode
        Stdout = $stdout
        Stderr = $stderr
    }
}

function Get-TfiForwardedEnvironmentArguments {
    $arguments = @()
    foreach ($name in $script:forwardedEnvironmentNames) {
        $value = [System.Environment]::GetEnvironmentVariable($name, "Process")
        if ($null -ne $value) {
            $arguments += @("-e", "$name=$value")
        }
    }
    return $arguments
}

function Test-TfiWorkerRunning {
    param([string]$Docker)

    $result = Invoke-TfiHiddenProcess -FilePath $Docker -Arguments @("compose", "--project-directory", $repoRoot, "ps", "--status", "running", "--services") -SuppressOutput
    if ($result.ExitCode -ne 0) {
        return $false
    }
    $services = @($result.Stdout -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    return $services -contains "worker"
}

function Get-TfiDockerCommand {
    $dockerExe = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $dockerExe) { return $dockerExe }
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($docker) { return $docker.Source }
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) { return $docker.Source }
    throw "docker.exe was not found. Install or start Docker Desktop."
}

$docker = Get-TfiDockerCommand

if (Test-TfiWorkerRunning -Docker $docker) {
    $execArgs = @("compose", "--project-directory", $repoRoot, "exec", "-T") + (Get-TfiForwardedEnvironmentArguments) + @("worker", "python", "-m", "timeline_for_image_worker") + @($CliArgs)
    $execResult = Invoke-TfiHiddenProcess -FilePath $docker -Arguments $execArgs -WriteOutput
    exit $execResult.ExitCode
}

$buildResult = Invoke-TfiHiddenProcess -FilePath $docker -Arguments @("compose", "--project-directory", $repoRoot, "build", "worker") -SuppressOutput
if ($buildResult.ExitCode -ne 0) {
    if ($buildResult.Stderr.Length -gt 0) { [Console]::Error.Write($buildResult.Stderr) }
    if ($buildResult.Stdout.Length -gt 0) { [Console]::Error.Write($buildResult.Stdout) }
    throw "Failed to build TimelineForImage worker."
}
$runResult = Invoke-TfiHiddenProcess -FilePath $docker -Arguments (@("compose", "--project-directory", $repoRoot, "run", "--rm", "--no-deps", "worker") + @($CliArgs)) -WriteOutput

exit $runResult.ExitCode
