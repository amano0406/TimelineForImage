$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

if (-not $env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT) {
    $env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT = "C:\"
}

if (-not $env:TIMELINE_FOR_IMAGE_OUTPUT_MOUNT) {
    $SettingsPath = Join-Path -Path $PSScriptRoot -ChildPath "settings.json"
    if (Test-Path -LiteralPath $SettingsPath) {
        try {
            $Settings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
            if ($Settings.outputs_root) {
                $env:TIMELINE_FOR_IMAGE_OUTPUT_MOUNT = [string] $Settings.outputs_root
            }
        }
        catch {
            $env:TIMELINE_FOR_IMAGE_OUTPUT_MOUNT = ""
        }
    }

    if (-not $env:TIMELINE_FOR_IMAGE_OUTPUT_MOUNT) {
        $env:TIMELINE_FOR_IMAGE_OUTPUT_MOUNT = "C:\Users\amano\image"
    }
}

$DockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
if (-not $DockerCommand) {
    $DockerCommand = Get-Command docker -CommandType Application -ErrorAction Stop
}

$ComposeArgs = @("compose", "--profile", "worker", "run", "--rm", "worker")
if ($args.Count -gt 0) {
    $ComposeArgs += $args
}

if ($env:WSLENV) {
    $Process = Start-Process -FilePath $DockerCommand.Path -ArgumentList $ComposeArgs -NoNewWindow -Wait -PassThru
    exit $Process.ExitCode
}

& $DockerCommand.Path @ComposeArgs
exit $LASTEXITCODE
