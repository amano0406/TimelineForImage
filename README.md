# TimelineForImage

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
  "inputRoots": [
    "C:\\TimelineData\\input-image\\"
  ],
  "outputRoot": "C:\\TimelineData\\image"
}
```

## Output

The main output is one `image_record.json` per image.

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

`cli.ps1` also starts the resident Docker worker when it is not already running, then executes commands inside that worker.

Stop the resident worker when needed:

```powershell
.\stop.ps1
```

## Sample

Committed sample input and sample output fixtures are planned. Current tests create temporary sample images and clean them up after validation.

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

## Detailed Docs

- [CLI](docs/CLI.md): read this for the command contract.
- [Outputs](docs/OUTPUTS.md): read this before consuming generated files.
- [Pipeline](docs/PIPELINE.md): read this to understand how image records are produced.
- [Runtime](docs/RUNTIME.md): read this for Docker, OCR, and third-party runtime notes.
- [Testing](docs/TESTING.md): read this before running validation locally or in CI.
- [Safety](docs/SAFETY.md): read this before operating on real image folders.
