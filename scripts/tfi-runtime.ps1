[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:TfiProductSlug = "timeline-for-image"
$script:TfiDefaultApiPort = 19400
$script:TfiSettingsFileName = "settings.json"
$script:TfiSettingsExampleFileName = "settings.example.json"
$script:TfiForwardedEnvironmentNames = @(
    "TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT",
    "TIMELINE_FOR_IMAGE_SETTINGS_PATH",
    "TIMELINE_FOR_IMAGE_SETTINGS_EXAMPLE_PATH",
    "TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT",
    "TIMELINE_FOR_IMAGE_WORKER_INTERVAL_SECONDS",
    "TIMELINE_FOR_IMAGE_INSTANCE_NAME",
    "TIMELINE_FOR_IMAGE_API_PORT"
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
    $startInfo.WorkingDirectory = $script:TfiRepoRoot
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
    foreach ($name in $script:TfiForwardedEnvironmentNames) {
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

function Get-TfiDockerCommand {
    $dockerExe = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $dockerExe) { return $dockerExe }
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($docker) { return $docker.Source }
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($docker) { return $docker.Source }
    throw "docker.exe was not found. Install or start Docker Desktop."
}

function Get-TfiObjectPropertyValue {
    param(
        [object]$Object,
        [string]$Name
    )

    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Normalize-TfiRuntimeName {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    $normalized = $Value.ToLowerInvariant() -replace '[^a-z0-9-]', '-'
    $normalized = $normalized -replace '-+', '-'
    return $normalized.Trim('-')
}

function New-TfiInstanceName {
    $bytes = [byte[]]::new(5)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

function ConvertTo-TfiApiPort {
    param([object]$Value)

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return $script:TfiDefaultApiPort
    }
    $port = 0
    if (-not [int]::TryParse([string]$Value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw "TIMELINE_FOR_IMAGE_API_PORT must be a TCP port from 1 to 65535."
    }
    return $port
}

function ConvertFrom-TfiWorkspacePath {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $text = $Value.Trim()
    if ($text.StartsWith("/workspace/", [System.StringComparison]::OrdinalIgnoreCase)) {
        return Join-Path $RepoRoot ($text.Substring("/workspace/".Length).Replace("/", "\"))
    }
    if ($text.Equals("/workspace", [System.StringComparison]::OrdinalIgnoreCase)) {
        return $RepoRoot
    }
    return $text
}

function Get-TfiSettingsHostPath {
    param([string]$RepoRoot)

    $configured = [System.Environment]::GetEnvironmentVariable("TIMELINE_FOR_IMAGE_SETTINGS_PATH", "Process")
    if (-not [string]::IsNullOrWhiteSpace($configured)) {
        return ConvertFrom-TfiWorkspacePath -RepoRoot $RepoRoot -Value $configured
    }
    return Join-Path $RepoRoot $script:TfiSettingsFileName
}

function Read-TfiJsonFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    try {
        return $raw | ConvertFrom-Json
    }
    catch {
        throw "$Path is not valid JSON: $($_.Exception.Message)"
    }
}

function New-TfiDefaultSettingsObject {
    param([string]$RepoRoot)

    $examplePath = Join-Path $RepoRoot $script:TfiSettingsExampleFileName
    $payload = Read-TfiJsonFile -Path $examplePath
    if ($null -ne $payload) {
        return $payload
    }
    return [pscustomobject]@{
        schemaVersion = 1
        runtime = [pscustomobject]@{
            instanceName = ""
            apiPort = $script:TfiDefaultApiPort
        }
        inputRoots = @("C:\TimelineData\input-image\")
        outputRoot = "C:\TimelineData\image"
        computeMode = "gpu"
    }
}

function ConvertTo-TfiOrderedSettingsObject {
    param([Parameter(Mandatory = $true)][object]$Settings)

    $ordered = [ordered]@{}
    foreach ($name in @("schemaVersion", "runtime", "inputRoots", "outputRoot", "huggingfaceToken", "computeMode")) {
        $property = $Settings.PSObject.Properties[$name]
        if ($null -ne $property) {
            $ordered[$name] = $property.Value
        }
    }
    foreach ($property in $Settings.PSObject.Properties) {
        if (-not $ordered.Contains($property.Name)) {
            $ordered[$property.Name] = $property.Value
        }
    }
    [pscustomobject]$ordered
}

function Set-TfiProcessEnvironmentValue {
    param(
        [string]$Name,
        [string]$Value
    )

    [System.Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    Set-Item -Path "Env:$Name" -Value $Value
}

function Initialize-TfiRuntimeEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [switch]$NoPersist
    )

    $script:TfiRepoRoot = $RepoRoot
    if (-not $env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT) {
        Set-TfiProcessEnvironmentValue -Name "TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT" -Value "C:\"
    }

    $settingsHostPath = Get-TfiSettingsHostPath -RepoRoot $RepoRoot
    $settings = Read-TfiJsonFile -Path $settingsHostPath
    if ($null -eq $settings) {
        $settings = New-TfiDefaultSettingsObject -RepoRoot $RepoRoot
    }

    $changed = $false
    if ($null -eq $settings.PSObject.Properties["computeMode"]) {
        Add-Member -InputObject $settings -MemberType NoteProperty -Name "computeMode" -Value "gpu"
        $changed = $true
    }
    if ($null -eq $settings.PSObject.Properties["runtime"]) {
        Add-Member -InputObject $settings -MemberType NoteProperty -Name "runtime" -Value ([pscustomobject]@{})
        $changed = $true
    }

    $envInstance = Normalize-TfiRuntimeName -Value ([string][System.Environment]::GetEnvironmentVariable("TIMELINE_FOR_IMAGE_INSTANCE_NAME", "Process"))
    $settingsInstance = Normalize-TfiRuntimeName -Value ([string](Get-TfiObjectPropertyValue -Object $settings.runtime -Name "instanceName"))
    $instanceName = if ($envInstance) { $envInstance } elseif ($settingsInstance) { $settingsInstance } elseif ($NoPersist) { "default" } else { New-TfiInstanceName }

    $envPort = [System.Environment]::GetEnvironmentVariable("TIMELINE_FOR_IMAGE_API_PORT", "Process")
    $settingsPort = Get-TfiObjectPropertyValue -Object $settings.runtime -Name "apiPort"
    $apiPort = if (-not [string]::IsNullOrWhiteSpace($envPort)) { ConvertTo-TfiApiPort -Value $envPort } else { ConvertTo-TfiApiPort -Value $settingsPort }

    if (-not $NoPersist) {
        $currentInstance = [string](Get-TfiObjectPropertyValue -Object $settings.runtime -Name "instanceName")
        $currentPort = Get-TfiObjectPropertyValue -Object $settings.runtime -Name "apiPort"
        if ($currentInstance -ne $instanceName -or [string]$currentPort -ne [string]$apiPort) {
            $settings.runtime = [ordered]@{
                instanceName = $instanceName
                apiPort = $apiPort
            }
            $changed = $true
        }
        if ($changed -or -not (Test-Path -LiteralPath $settingsHostPath)) {
            $parent = Split-Path -Parent $settingsHostPath
            if ($parent) {
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
            }
            $settings = ConvertTo-TfiOrderedSettingsObject -Settings $settings
            $json = $settings | ConvertTo-Json -Depth 20
            $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
            [System.IO.File]::WriteAllText($settingsHostPath, $json + [Environment]::NewLine, $utf8NoBom)
        }
    }

    Set-TfiProcessEnvironmentValue -Name "TIMELINE_FOR_IMAGE_INSTANCE_NAME" -Value $instanceName
    Set-TfiProcessEnvironmentValue -Name "TIMELINE_FOR_IMAGE_API_PORT" -Value ([string]$apiPort)

    $composeProject = "$($script:TfiProductSlug)-$instanceName"
    [pscustomobject]@{
        InstanceName = $instanceName
        ApiPort = $apiPort
        ApiBaseUrl = "http://127.0.0.1:$apiPort"
        ComposeProject = $composeProject
        SettingsHostPath = $settingsHostPath
    }
}

function Get-TfiComposeArguments {
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][object]$Runtime,
        [string[]]$Arguments = @()
    )

    return @("compose", "--project-directory", $RepoRoot, "-p", ([string]$Runtime.ComposeProject)) + @($Arguments)
}

function Get-TfiExecEnvironmentArguments {
    $arguments = @()
    foreach ($name in $script:TfiForwardedEnvironmentNames) {
        $value = [System.Environment]::GetEnvironmentVariable($name, "Process")
        if ($null -ne $value) {
            $arguments += @("-e", "$name=$value")
        }
    }
    return $arguments
}
