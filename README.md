# TimelineForImage

`TimelineForImage` converts local image files into timeline-oriented Markdown, JSON, and ZIP packages that are easier to hand to ChatGPT or other LLM tools.

This product is local-first and CLI-only. It does not edit source images.

## Current Scope

The first implementation keeps host execution lightweight and puts model dependencies in the Docker Compose worker. It extracts:

- source path
- SHA-256 digest
- file size
- image format
- width and height
- EXIF capture timestamp when available
- EXIF camera make/model, lens model, focal length, and GPS coordinates when available
- file modified timestamp fallback
- metadata warnings when capture time or dimensions are unavailable
- image-to-text descriptions through a local Hugging Face model in the worker container by default
- local OCR through Tesseract in the worker container
- derived visual observations from captions/OCR
- day-based timeline grouping
- optional human annotations from a JSON file
- deterministic `mock` captions for tests and dry runs
- optional OpenAI image captions when `--caption-mode openai` and `OPENAI_API_KEY` are set

It does not yet perform face recognition or person identity matching.

## Source Model

You can pass input paths per command, or register one or more master source directories:

```bash
docker compose --profile worker run --rm worker sources add /mnt/c/path/to/images

docker compose --profile worker run --rm worker sources list
```

After sources are registered, `discover`, `create-job`, and `run` can be executed without `--directory`.

`settings.json` also accepts multiple sources. `recursive` is evaluated per source.

```json
{
  "sources": [
    {
      "path": "C:\\Users\\amano\\Pictures\\",
      "recursive": true
    },
    {
      "path": "C:\\Users\\amano\\Desktop\\camera-import\\",
      "recursive": false
    }
  ]
}
```

Each run compares discovered images with the master catalog and records:

- `new`
- `changed`
- `unchanged`

The base processing profile is `metadata-v2`. Caption/OCR modes and models are included in the effective profile so conversion changes are visible as changed work.

Derived outputs are cached under the configured state root in `derived_cache.json`. When an image SHA-256 and processing profile match a previous run, caption, OCR, and visual observation records are reused instead of regenerated.

## Settings

Persistent settings live in `settings.json` at the repository root. `settings.example.json` is the tracked template; `settings.json` is local-only and ignored by Git.

Create `settings.json` when it does not exist:

```bash
docker compose --profile worker run --rm worker settings init
```

Current defaults:

```json
{
  "sources": [
    {
      "path": "C:\\Users\\amano\\Pictures\\",
      "recursive": true
    }
  ],
  "outputs_root": "C:\\Users\\amano\\image\\",
  "appdata_root": "C:\\Users\\amano\\image\\.timeline-for-image-state",
  "caption": {
    "mode": "local",
    "model": "Salesforce/blip-image-captioning-base"
  },
  "ocr": {
    "mode": "auto",
    "model": "tesseract:eng+jpn"
  },
  "watch": {
    "interval_seconds": 30,
    "min_quiet_seconds": 2
  },
  "mock": false
}
```

On Docker/Linux, `C:\...` paths are normalized to `/mnt/c/...`. The Compose worker reads `settings.json`.

The worker always sees the C drive at `/mnt/c`. The Windows PowerShell front door sets the Docker bind source to `C:\`; the WSL/Linux back door defaults it to `/mnt/c`. The output bind source defaults to `C:\Users\amano\image\` on Windows and `/mnt/c/Users/amano/image` from WSL/Linux. If inputs or outputs live on another drive, set `TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT` / `TIMELINE_FOR_IMAGE_OUTPUT_MOUNT` or add another mount in `docker-compose.yml`.

```bash
docker compose --profile worker up worker
```

Preflight check:

```bash
docker compose --profile worker run --rm worker doctor --format json
```

`doctor` checks settings presence, source visibility, output/state writability, Docker execution guard state, the Hugging Face local backend, and Tesseract OCR languages.

## Watch and Latest Output

`watch` scans sources and only creates a run when discovered images are new or changed for the active processing profile.

```bash
docker compose --profile worker run --rm worker watch \
  --directory /mnt/c/path/to/images \
  --once \
  --min-quiet-seconds 0
```

Using `settings.json`:

```bash
docker compose --profile worker run --rm worker watch \
  --once
```

Without `--once`, `watch` repeats at `--interval-seconds`. `--min-quiet-seconds` prevents processing files that are still being written.

Every completed `run` or `watch` execution updates `<outputs-root>/latest/` with stable paths:

- `latest/timeline.md`
- `latest/result.json`
- `latest/TimelineForImage-export.zip`

## Image Captions

The default caption mode is `local`. It uses a Hugging Face `image-to-text` model inside the Docker Compose `worker` container.

```bash
docker compose --profile worker run --rm worker run --directory /mnt/c/path/to/images
```

Defaults:

- description model: `Salesforce/blip-image-captioning-base`
- OCR engine: `tesseract:eng+jpn`

Run the worker in Docker:

```bash
docker compose --profile worker run --rm worker doctor
docker compose --profile worker run --rm worker run --directory /mnt/c/path/to/images
```

On Windows, `start.ps1` is the primary entry point. `start.bat` remains a compatibility shim that delegates to PowerShell. `start.command` is kept as the WSL/Linux back door. Direct host Python CLI execution is disabled by default.

Override them with:

```bash
TIMELINE_FOR_IMAGE_LOCAL_MODEL=Salesforce/blip-image-captioning-base \
TIMELINE_FOR_IMAGE_OCR_MODEL=tesseract:eng+jpn \
docker compose --profile worker run --rm worker run --directory /mnt/c/path/to/images
```

Use deterministic mock captions for tests:

```bash
docker compose --profile worker run --rm worker run \
  --directory /mnt/c/path/to/images \
  --caption-mode mock
```

Use OpenAI captions when an API key is available:

```bash
OPENAI_API_KEY=... \
docker compose --profile worker run --rm worker run \
  --directory /mnt/c/path/to/images \
  --caption-mode openai
```

You can override the provisional model:

```bash
docker compose --profile worker run --rm worker run \
  --directory /mnt/c/path/to/images \
  --caption-mode openai \
  --caption-model gpt-4o-mini
```

Captions are stored as derived evidence in `captions.json` and copied into `timeline.md`. They are not treated as observed facts.

## OCR

OCR is separate from image description.

Default OCR mode is `auto`:

1. run local OCR in the worker container
2. treat non-empty OCR text as the current auto-mode check result
3. write `ocr.json`
4. copy the OCR decision and extracted text into `timeline.md`

Modes:

- `--ocr-mode off`
- `--ocr-mode auto`
- `--ocr-mode always`
- `--ocr-mode mock`

The OCR check and OCR text are derived evidence. They can be wrong and should be reviewed.

## Visual Observations, Grouping, and Annotations

`visual_observations.json` is derived from captions and OCR. It currently records coarse fields such as:

- people presence estimate
- text presence
- place hint
- visible object keywords
- activity keywords

`timeline_groups.json` currently emits day, sequence, event, and location groups. Sequence groups are created when adjacent timeline timestamps are within 10 minutes. Event groups come from matching human annotation `event` values. Location groups are created when GPS coordinates are within 250 meters. This is heuristic timeline reasoning and will be expanded later for richer event inference.

Human annotations can be supplied with `--annotations-file`:

```json
{
  "annotations": [
    {
      "relative_path": "sample.png",
      "tags": ["receipt"],
      "people": ["person name"],
      "event": "trip",
      "note": "manual note"
    }
  ]
}
```

Annotations are copied into `annotations.json` and shown in `timeline.md`.

## Output Layout

Each run writes a run directory under the configured outputs root:

```text
<outputs-root>/
  <run-id>/
    request.json
    status.json
    result.json
    manifest.json
    catalog.json
    timeline.md
    fidelity_report.md
    export/TimelineForImage-export.zip
```

The shared state root also contains `master_catalog.json` and `derived_cache.json`.

The ZIP contains:

- `README.md`
- `timeline.md`
- `catalog.json`
- `captions.json`
- `ocr.json`
- `visual_observations.json`
- `timeline_groups.json`
- `annotations.json`
- `manifest.json`
- `fidelity_report.md`

Original image files are not included in the ZIP.

## Supported Input Formats

- `.jpg`
- `.jpeg`
- `.png`
- `.gif`
- `.webp`
- `.bmp`

## Quick Start

From the repository root on Windows PowerShell:

```powershell
.\start.ps1 discover --directory C:\path\to\images
.\start.ps1 run --directory C:\path\to\images
```

`start.bat` is available only as a compatibility shim. From WSL/Linux, `./start.command` can be used as a back-door wrapper around the same Docker Compose worker.

The lower-level Docker Compose form is also available:

```bash
docker compose --profile worker run --rm worker discover --directory /mnt/c/path/to/images
```

Create an export:

```bash
docker compose --profile worker run --rm worker run --directory /mnt/c/path/to/images --format json
```

Inspect previous runs:

```bash
docker compose --profile worker run --rm worker list-jobs

docker compose --profile worker run --rm worker show-job <run-id>

docker compose --profile worker run --rm worker doctor
```

## Local Data

With `settings.json`, outputs and state use:

- `outputs_root`
- `appdata_root`

If neither settings nor environment variables are present, the CLI falls back to:

- Windows: `%LOCALAPPDATA%\TimelineForImage\outputs`
- Unix-like environments: `~/.timeline-for-image/outputs`

You can override this with:

- `TIMELINE_FOR_IMAGE_APPDATA_ROOT`
- `TIMELINE_FOR_IMAGE_OUTPUTS_ROOT`
- `TIMELINE_FOR_IMAGE_SETTINGS_PATH`
- `TIMELINE_FOR_IMAGE_SETTINGS_EXAMPLE_PATH`
- `TIMELINE_FOR_IMAGE_LOCAL_MODEL`
- `TIMELINE_FOR_IMAGE_OCR_MODEL`
- `TIMELINE_FOR_IMAGE_CAPTION_MODEL`

## Mock Mode

Use `--mock` with `discover` or `run` to create deterministic placeholder image records without reading image files:

```bash
docker compose --profile worker run --rm worker run --directory /mnt/c/path/to/images --mock
```

Mock mode is for tests and dry runs. It must remain dependency-free.

## Testing

Run tests in the worker container. Direct host CLI execution is only allowed when `TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI=1` is explicitly set for tests.

```bash
docker compose --profile worker run --rm --entrypoint sh worker -c \
  "pip install --no-cache-dir pytest >/tmp/pip-test.log && PYTHONPATH=/app/worker/src python -m pytest /app-config/worker/tests"
```
