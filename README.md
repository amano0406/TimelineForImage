# TimelineForImage

## Current Status

TimelineForImage is currently a Docker-first CLI product. Starting the Docker
runtime does not process images automatically; image processing starts only when
you run an explicit CLI command such as `items refresh` or `serve --once`. The broad API
migration has been rolled back; the only HTTP API intentionally exposed by this
product is the local C# health endpoint:

```text
GET /health
```

All image processing, listing, download, removal, run inspection, and
maintenance operations are covered by `cli.ps1`.

## What This Product Does

TimelineForImage converts local image files into per-image `image_record.json` and `timeline.json` records. It is a local Docker-first CLI worker for downstream Timeline, search, handoff, and LLM workflows. It does not edit source images or perform person recognition.

## Input

The user provides one or more local image folders through `settings.json`.

Supported image extensions:

```text
.jpg .jpeg .png .webp .bmp .gif .tif .tiff
```

Default settings template:

```json
{
  "schemaVersion": 1,
  "runtime": {
    "instanceName": "",
    "apiPort": 19400
  },
  "inputRoots": [
    "C:\\TimelineData\\input-image\\"
  ],
  "outputRoot": "C:\\TimelineData\\image",
  "huggingfaceToken": "hf_...",
  "computeMode": "gpu"
}
```

`start.ps1` and `cli.ps1` fill `runtime.instanceName` when it is empty. If the
product uses a Hugging Face token, store it as `huggingfaceToken`; omit the key
when no token is needed.

## Output

The main output is one `image_record.json` per image. See
[Outputs](docs/OUTPUTS.md) for concrete JSON structures and data examples.

```text
<outputRoot>/
  items/
    <item-id>/
      image_record.json
      timeline.json
      convert_info.json
      raw_outputs/
        ocr.json
      artifacts/
        normalized_image.jpg
        debug_overlay.jpg
  downloads/
    TimelineForImage-export-<timestamp>-<id>.zip
    TimelineForImage-selected.zip
  latest/
    TimelineForImage-export.zip
```

Export ZIPs do not include original source images.

## Quick Start

Run from PowerShell in `C:\apps\TimelineForImage`.

```powershell
.\start.ps1
.\cli.ps1 settings init
.\cli.ps1 settings save --input-root C:\TimelineData\input-image --output-root C:\TimelineData\image
.\cli.ps1 doctor
.\cli.ps1 items refresh --max-items 4
.\cli.ps1 items list
.\cli.ps1 items download
```

If the local PowerShell execution policy blocks scripts, run through
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File` or use the provided
batch wrappers where available.

`start.bat` and `stop.bat` are also available as Windows command prompt / Explorer-friendly wrappers around the PowerShell launchers.

`start.ps1` starts the resident runtime and health endpoint only. It does not
start image processing. `cli.ps1` also starts the resident Docker worker when it
is not already running, then executes commands inside that worker.

The worker also exposes a minimal local C# health endpoint on the configured
port:

```powershell
curl.exe http://127.0.0.1:19400/health
```

The response is the JSON boolean `true` or `false`.

No other HTTP API routes are part of the current contract. For example,
`/image/*` routes are intentionally not available.

Stop the resident worker when needed:

```powershell
.\stop.ps1
```

## Sample

Current tests create temporary sample images and clean them up after validation.

## Common Commands

```powershell
.\cli.ps1 files list
.\cli.ps1 items refresh
.\cli.ps1 items refresh --max-items 4
.\cli.ps1 items list --page 1 --page-size 50
.\cli.ps1 items download
.\cli.ps1 items download --item-id image-xxxxxxxxxxxxxxxx
.\cli.ps1 items download --to C:\path\handoff --overwrite
.\cli.ps1 items remove --item-id image-xxxxxxxxxxxxxxxx --dry-run
.\cli.ps1 items remove --item-id image-xxxxxxxxxxxxxxxx
.\cli.ps1 runs list
.\cli.ps1 runs show --run-id <RUN_ID>
.\cli.ps1 health
.\cli.ps1 doctor
.\cli.ps1 maintenance cleanup --dry-run
```

`items remove` deletes generated item artifacts and catalog entries only. It
does not delete source image files.

## Validation

Use these commands for local validation:

```powershell
dotnet build health\TimelineForImage.Health\TimelineForImage.Health.csproj
python -m unittest discover -s tests
docker compose --project-directory . -p timeline-for-image-unit run --rm --entrypoint sh worker -c "pip install --quiet -e /workspace/worker pytest jsonschema pillow && PYTHONPATH=/workspace/worker/src python -m pytest /workspace/worker/tests -q"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-operational.ps1
```

The operational test uses isolated settings, input, output, state, and Docker
project names. It does not use the root `settings.json`.

## Detailed Docs

- [CLI](docs/CLI.md): read this for the command contract.
- [Outputs](docs/OUTPUTS.md): read this before consuming generated files.
- [Runtime](docs/RUNTIME.md): read this for Docker, pipeline, OCR, and safety notes.
- [Testing](docs/TESTING.md): read this before running validation locally or in CI.
