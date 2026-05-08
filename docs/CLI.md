# CLI

[Back to README](../README.md)

TimelineForImage is operated through the launchers in the repository root. Normal users should use `start.ps1`, `stop.ps1`, and `cli.ps1`; `start.bat` and `stop.bat` are Windows command prompt / Explorer-friendly wrappers. Host Python execution is not the supported entry point.

## Worker Lifecycle

```powershell
.\start.ps1
.\stop.ps1
```

Equivalent command prompt wrappers:

```cmd
start.bat
stop.bat
```

`start.ps1` starts the Docker Compose worker in the background. `cli.ps1` runs commands inside the resident worker when it is available.

If the worker is not running, `cli.ps1` starts the resident Docker Compose project first and then executes the command with `docker compose exec`. Normal product commands should not create one-off `worker-run-*` containers.

## Settings

```powershell
.\cli.ps1 settings init
.\cli.ps1 settings status
.\cli.ps1 settings save --input-root C:\TimelineData\input-image --output-root C:\TimelineData\image
```

`settings.json` contains only:

- `schemaVersion`
- `inputRoots`
- `outputRoot`

Internal state, cache, OCR configuration, and test paths are not user-facing settings.

## Discovery and Processing

```powershell
.\cli.ps1 files list
.\cli.ps1 items refresh
.\cli.ps1 items refresh --max-items 4
.\cli.ps1 items refresh --reprocess-duplicates
.\cli.ps1 items list
.\cli.ps1 items list --page 1 --page-size 50
```

`items refresh` processes new or changed images. Unchanged images are skipped.

## Download

```powershell
.\cli.ps1 items download
.\cli.ps1 items download --item-id image-xxxxxxxxxxxxxxxx
.\cli.ps1 items download --to C:\path\handoff --overwrite
```

`items download` creates a handoff ZIP from the current item set. Use `--item-id` to limit the export to specific items.

## Remove Generated Artifacts

```powershell
.\cli.ps1 items remove --item-id image-xxxxxxxxxxxxxxxx --dry-run
.\cli.ps1 items remove --item-id image-xxxxxxxxxxxxxxxx
```

`items remove` deletes generated item artifacts and catalog entries. It does not delete source image files.

## Runs and Maintenance

```powershell
.\cli.ps1 runs list
.\cli.ps1 runs show --run-id <RUN_ID>
.\cli.ps1 health
.\cli.ps1 doctor
.\cli.ps1 models list
.\cli.ps1 maintenance cleanup --dry-run
.\cli.ps1 maintenance cleanup --keep-runs 100 --keep-downloads 20
```

`health` is a lightweight worker health command. `doctor` validates settings, paths, and OCR readiness. `maintenance cleanup` removes old run directories and generated export ZIPs according to the retention values.
