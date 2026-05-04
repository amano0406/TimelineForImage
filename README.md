# TimelineForImage

Local Docker-first CLI for converting image files into per-image `image_record.json` and `timeline.json` artifacts.

This file is the repository entry point. The canonical operation guide is [README.ja.md](README.ja.md).

## Product Role

`TimelineForImage` is the image sub-product in the Timeline product family.

Its job is to turn local image files into stable structured records that later tools, LLM workflows, search indexes, and handoff processes can consume. It is not an image viewer, photo library, annotation UI, cloud vision service, or person-recognition product.

The product is intentionally narrow:

- read images from configured local folders
- preserve original image files
- create durable per-image records
- expose stable JSON contracts
- run locally through Docker-first PowerShell entry points

## Design Principles

- Local-first: default processing stays on the local machine.
- Source-preserving: original image files are never edited.
- Contract-first: `settings.json` and `image_record.json` are governed by schemas.
- Operation-first: the normal interface is a resident Docker worker plus `cli.ps1`.
- Boundary-first: advanced semantic grouping, similar-image search, privacy masking, and person clustering are outside the current responsibility.

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
.\cli.ps1 items download
.\stop.ps1
```

Do not run the host Python package directly for normal operation. The worker is intended to run inside Docker Compose.

## Product Boundaries

- Original images are not modified.
- Export ZIPs do not include original images.
- OCR text is not privacy-redacted.
- Person identity recognition and face recognition are not performed.
- The default worker does not send images to external APIs.
