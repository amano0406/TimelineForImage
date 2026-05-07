[CmdletBinding()]
param(
    [switch]$KeepOutput,
    [string]$WorkRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $WorkRoot) {
    $WorkRoot = Join-Path $repoRoot "output\operational-test\current"
}

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

function Invoke-TfiProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [hashtable]$Environment = @()
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

    foreach ($key in $Environment.Keys) {
        $startInfo.EnvironmentVariables[[string]$key] = [string]$Environment[$key]
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()

    return [pscustomobject]@{
        ExitCode = [int]$process.ExitCode
        Stdout = [string]$stdoutTask.Result
        Stderr = [string]$stderrTask.Result
    }
}

function Get-TfiPowerShellCommand {
    $powershell = Get-Command powershell.exe -ErrorAction SilentlyContinue
    if ($powershell) { return $powershell.Source }
    $pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
    if ($pwsh) { return $pwsh.Source }
    throw "PowerShell executable was not found."
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

function ConvertTo-TfiWorkspacePath {
    param([string]$WindowsPath)

    $full = [System.IO.Path]::GetFullPath($WindowsPath)
    $repo = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd('\')
    if (-not $full.StartsWith($repo, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside repo root: $full"
    }
    $relative = $full.Substring($repo.Length).TrimStart('\').Replace('\', '/')
    if ($relative.Length -eq 0) { return "/workspace" }
    return "/workspace/$relative"
}

function ConvertFrom-TfiContainerPath {
    param([string]$ContainerPath)

    if ($ContainerPath -match '^/workspace(?:/(.*))?$') {
        $relative = $Matches[1]
        if (-not $relative) { return $repoRoot }
        return Join-Path $repoRoot ($relative.Replace('/', '\'))
    }
    if ($ContainerPath -match '^/mnt/([a-zA-Z])/(.*)$') {
        $drive = $Matches[1].ToUpperInvariant()
        $rest = $Matches[2].Replace('/', '\')
        return "${drive}:\$rest"
    }
    return $ContainerPath
}

function New-TfiSamplePng {
    param([Parameter(Mandatory = $true)][string]$Path)

    $base64 = "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAGCAIAAABxZ0isAAAAD0lEQVR4nGP4jwMwDKQEAAjcj3FNTHRjAAAAAElFTkSuQmCC"
    [System.IO.File]::WriteAllBytes($Path, [Convert]::FromBase64String($base64))
}

function Assert-Tfi {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Assert-TfiRepoSettingsUnchanged {
    if ($script:repoSettingsHadOriginal) {
        Assert-Tfi (Test-Path -LiteralPath $script:repoSettingsPath) "Repo settings.json was removed during operational test."
        $current = [System.IO.File]::ReadAllBytes($script:repoSettingsPath)
        Assert-Tfi (
            [Convert]::ToBase64String($current) -eq [Convert]::ToBase64String($script:repoSettingsOriginalBytes)
        ) "Repo settings.json was modified during operational test."
        return
    }
    Assert-Tfi (-not (Test-Path -LiteralPath $script:repoSettingsPath)) "Repo settings.json was created during operational test."
}

function Invoke-TfiCli {
    param([string[]]$Arguments)

    $result = Invoke-TfiProcess `
        -FilePath $script:powershell `
        -Arguments (@("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $repoRoot "cli.ps1")) + $Arguments) `
        -Environment $script:testEnvironment
    if ($result.ExitCode -ne 0) {
        throw "cli.ps1 failed ($($Arguments -join ' '))`nstdout:`n$($result.Stdout)`nstderr:`n$($result.Stderr)"
    }
    return $result
}

function Invoke-TfiCliJson {
    param([string[]]$Arguments)

    $result = Invoke-TfiCli -Arguments (@("--json") + $Arguments)
    try {
        return $result.Stdout | ConvertFrom-Json
    }
    catch {
        throw "CLI output was not JSON ($($Arguments -join ' '))`nstdout:`n$($result.Stdout)`nstderr:`n$($result.Stderr)"
    }
}

function Test-TfiComposeWorkerRunning {
    param([string]$Docker)

    $result = Invoke-TfiProcess `
        -FilePath $Docker `
        -Arguments @("compose", "--project-directory", $repoRoot, "ps", "--status", "running", "--services") `
        -Environment $script:testEnvironment
    if ($result.ExitCode -ne 0) {
        return $false
    }

    $services = @($result.Stdout -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    return $services -contains "worker"
}

function Stop-TfiCompose {
    param([string]$Docker)

    [void](Invoke-TfiProcess `
        -FilePath $Docker `
        -Arguments @("compose", "--project-directory", $repoRoot, "down") `
        -Environment $script:testEnvironment)
}

$success = $false
$powershell = Get-TfiPowerShellCommand
$workRootFull = [System.IO.Path]::GetFullPath($WorkRoot)
$inputRoot = Join-Path $workRootFull "input"
$outputRoot = Join-Path $workRootFull "records"
$stateRoot = Join-Path $workRootFull "state"
$settingsPath = Join-Path $workRootFull "settings.json"
$repoSettingsPath = Join-Path $repoRoot "settings.json"
$repoSettingsHadOriginal = Test-Path -LiteralPath $repoSettingsPath
$repoSettingsOriginalBytes = if ($repoSettingsHadOriginal) { [System.IO.File]::ReadAllBytes($repoSettingsPath) } else { [byte[]]@() }

$testEnvironment = @{
    "TIMELINE_FOR_IMAGE_SETTINGS_PATH" = (ConvertTo-TfiWorkspacePath -WindowsPath $settingsPath)
    "TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT" = (ConvertTo-TfiWorkspacePath -WindowsPath $stateRoot)
    "TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT" = "C:\"
}
$docker = Get-TfiDockerCommand
$workerWasRunningBeforeTest = Test-TfiComposeWorkerRunning -Docker $docker

try {
    if (Test-Path -LiteralPath $workRootFull) {
        Remove-Item -LiteralPath $workRootFull -Recurse -Force
    }
    New-Item -ItemType Directory -Path $inputRoot -Force | Out-Null
    New-TfiSamplePng -Path (Join-Path $inputRoot "sample-a.png")
    New-TfiSamplePng -Path (Join-Path $inputRoot "sample-b.png")

    Write-Host "Operational test root: $workRootFull"

    Invoke-TfiCli -Arguments @("settings", "save", "--input-root", $inputRoot, "--output-root", $outputRoot) | Out-Null
    Assert-Tfi (Test-Path -LiteralPath $settingsPath) "Test settings.json was not created."
    Assert-TfiRepoSettingsUnchanged

    $doctor = Invoke-TfiCliJson -Arguments @("doctor")
    Assert-Tfi ([bool]$doctor.ok) "doctor did not report ok."
    Assert-Tfi ($doctor.input_roots[0].supported_image_count -eq 2) "doctor did not see both sample images."

    $files = Invoke-TfiCliJson -Arguments @("files", "list", "--page", "1", "--page-size", "10")
    Assert-Tfi ($files.count -eq 2) "files list count was not 2."

    $refresh = Invoke-TfiCliJson -Arguments @("items", "refresh", "--max-items", "2", "--reprocess-duplicates")
    Assert-Tfi ($refresh.processed_count -eq 2) "refresh did not process 2 items."
    Assert-Tfi ($refresh.failed_count -eq 0) "refresh reported failures."
    Assert-Tfi (Test-Path -LiteralPath (Join-Path $stateRoot "catalog.json")) "Internal state catalog was not created in the test state root."

    $secondRefresh = Invoke-TfiCliJson -Arguments @("items", "refresh")
    Assert-Tfi ($secondRefresh.state -eq "skipped_no_changes") "second refresh should report skipped_no_changes."
    Assert-Tfi ($null -eq $secondRefresh.run_id) "second refresh should not create a run."
    Assert-Tfi ($secondRefresh.processed_count -eq 0) "second refresh should skip already processed items."
    Assert-Tfi ($secondRefresh.skipped_count -eq 2) "second refresh skipped count was not 2."

    $extraRefresh = Invoke-TfiCliJson -Arguments @("items", "refresh", "--max-items", "1", "--reprocess-duplicates")
    Assert-Tfi ($extraRefresh.processed_count -eq 1) "reprocess refresh did not process 1 item."
    Assert-Tfi ($extraRefresh.failed_count -eq 0) "reprocess refresh reported failures."

    $items = Invoke-TfiCliJson -Arguments @("items", "list", "--page", "1", "--page-size", "10")
    Assert-Tfi ($items.count -eq 2) "items list count was not 2."
    $firstItem = $items.items[0]
    Assert-Tfi ($null -ne $firstItem.item_id) "first item did not have an item_id."

    $runs = Invoke-TfiCliJson -Arguments @("runs", "list", "--page", "1", "--page-size", "10")
    Assert-Tfi ($runs.count -ge 1) "runs list did not include expected runs."

    $run = Invoke-TfiCliJson -Arguments @("runs", "show", "--run-id", $refresh.run_id)
    Assert-Tfi ($run.result.processed_count -eq 2) "runs show did not report 2 processed items."

    $download = Invoke-TfiCliJson -Arguments @("items", "download")
    $archivePath = ConvertFrom-TfiContainerPath -ContainerPath ([string]$download.archive_path)
    Assert-Tfi (Test-Path -LiteralPath $archivePath) "download archive was not created: $archivePath"

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        $entryNames = @($archive.Entries | ForEach-Object { $_.FullName })
    }
    finally {
        $archive.Dispose()
    }
    Assert-Tfi ($entryNames -contains "README.md") "download archive did not contain README.md."
    Assert-Tfi ([bool]($entryNames | Where-Object { $_ -like "items/*/image_record.json" })) "download archive did not contain image_record.json."
    Assert-Tfi (-not [bool]($entryNames | Where-Object { $_ -like "*.png" })) "download archive unexpectedly contained source images."

    $cleanupDryRun = Invoke-TfiCliJson -Arguments @("maintenance", "cleanup", "--keep-runs", "1", "--keep-downloads", "1", "--dry-run")
    Assert-Tfi ([bool]$cleanupDryRun.dry_run) "maintenance cleanup did not report dry_run."
    Assert-Tfi ($cleanupDryRun.runs.removed_count -ge 1) "maintenance cleanup did not identify old runs."
    Assert-Tfi ($cleanupDryRun.downloads.removed_count -ge 1) "maintenance cleanup did not identify old downloads."
    Assert-Tfi (Test-Path -LiteralPath $archivePath) "maintenance cleanup dry-run deleted the selected download archive."

    $itemDir = ConvertFrom-TfiContainerPath -ContainerPath ([string]$firstItem.output_dir)
    Assert-Tfi (Test-Path -LiteralPath $itemDir) "item output directory did not exist before remove."

    $dryRunRemove = Invoke-TfiCliJson -Arguments @("items", "remove", "--item-id", $firstItem.item_id, "--dry-run")
    Assert-Tfi ($dryRunRemove.removed_count -eq 1) "dry-run remove did not select 1 item."
    Assert-Tfi (Test-Path -LiteralPath $itemDir) "dry-run remove deleted the item directory."

    $remove = Invoke-TfiCliJson -Arguments @("items", "remove", "--item-id", $firstItem.item_id)
    Assert-Tfi ($remove.removed_count -eq 1) "remove did not remove 1 item."
    Assert-Tfi (-not (Test-Path -LiteralPath $itemDir)) "remove left the item directory in place."
    Assert-Tfi (Test-Path -LiteralPath (Join-Path $inputRoot "sample-a.png")) "remove deleted a source image."
    Assert-Tfi (Test-Path -LiteralPath (Join-Path $inputRoot "sample-b.png")) "remove deleted a source image."

    $afterRemove = Invoke-TfiCliJson -Arguments @("items", "list")
    Assert-Tfi ($afterRemove.count -eq 1) "items list count after remove was not 1."
    Assert-TfiRepoSettingsUnchanged

    $success = $true
    Write-Host "Operational test passed."
}
finally {
    if (-not $workerWasRunningBeforeTest) {
        Stop-TfiCompose -Docker $docker
    }
    if ($success -and -not $KeepOutput) {
        Remove-Item -LiteralPath $workRootFull -Recurse -Force -ErrorAction SilentlyContinue
    }
    elseif (-not $success) {
        Write-Warning "Operational test output kept for debugging: $workRootFull"
    }
}
