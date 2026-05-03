# TimelineForImage

Local Docker-first CLI for converting image files into per-image `image_record.json` and `timeline.json` artifacts.

This file is the repository entry point. The canonical operation guide is [README.ja.md](README.ja.md).

## Documentation Map

| File | Role |
| --- | --- |
| [README.md](README.md) | Short repository entry point and documentation routing. |
| [README.ja.md](README.ja.md) | Primary product documentation: settings, output contract, CLI, operations, and tests. |
| [MODEL_AND_RUNTIME_NOTES.md](MODEL_AND_RUNTIME_NOTES.md) | Runtime and model/backend notes. |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Third-party component notice. |
| [schemas/settings.schema.json](schemas/settings.schema.json) | Machine-readable `settings.json` contract. |
| [schemas/image_record.schema.json](schemas/image_record.schema.json) | Machine-readable `image_record.json` contract. |

## Operating Entry Points

Use the bundled PowerShell launchers from `C:\apps\TimelineForImage`.

```powershell
.\start.ps1
.\cli.ps1 doctor
.\cli.ps1 items refresh --max-items 4
.\cli.ps1 items list
.\cli.ps1 items download --all
.\stop.ps1
```

Do not run the host Python package directly for normal operation. The worker is intended to run inside Docker Compose.

## Product Boundaries

- Original images are not modified.
- Export ZIPs do not include original images.
- OCR text is not privacy-redacted.
- Person identity recognition and face recognition are not performed.
- The default worker does not send images to external APIs.
