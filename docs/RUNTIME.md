# Runtime

[Back to README](../README.md)

TimelineForImage is a Docker-first local CLI product.

## Required Runtime

- Windows PowerShell entry points: `start.ps1`, `stop.ps1`, `cli.ps1`
- Docker Desktop or compatible Docker Compose runtime
- Worker image built from `docker/worker.Dockerfile`

The normal command path is PowerShell to a resident Docker Compose worker to the Python CLI module:

```text
cli.ps1 -> docker compose up -d --build when needed -> docker compose exec -T worker python -m timeline_for_image_worker
```

Product commands use the resident worker container. One-off worker containers are reserved for isolated test harnesses, not normal operation.

## Docker Resources

```text
app-data     Internal runtime state
cache-data   OCR and future model cache
C:\ bind     Local Windows path access inside the container
```

## Pipeline

The worker processes each image independently:

1. Load `settings.json`.
2. Resolve configured input and output paths.
3. Discover supported image files.
4. Read file identity, SHA-256, dimensions, EXIF camera data, and timestamps.
5. Skip images that do not need processing.
6. Run local OCR.
7. Extract color palette, brightness, contrast, and a 3x3 color grid.
8. Write `image_record.json`, `timeline.json`, `convert_info.json`, normalized image, and debug overlay.
9. Update the internal catalog and run status.
10. Create export ZIPs when processing or download commands request them.

Skip behavior uses source hash, source file identity, generation signature, current output root, and required artifact presence.

## OCR and Image Processing

The default worker uses local metadata extraction and local Tesseract OCR. The default worker does not call an external image API.

## Third-Party Components

The worker container uses local open-source components:

- Pillow
- pytesseract
- Tesseract OCR

Original image files are not included in export ZIPs.

## Model Notes

`models list` reports available local processing components. The current default pipeline is local metadata, local image feature extraction, and local OCR.

## Safety Boundaries

- Source images are not edited.
- `items remove` deletes generated item artifacts and catalog entries only.
- Download ZIPs do not include original source image files.
- OCR text is preserved in generated records and is not privacy-masked.
- The product does not perform person identity recognition, face recognition, age inference, gender inference, or person clustering.
- The default worker does not send images to external APIs.
