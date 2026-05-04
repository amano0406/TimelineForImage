# Runtime

[Back to README](../README.md)

TimelineForImage is a Docker-first local CLI product.

## Required Runtime

- Windows PowerShell entry points: `start.ps1`, `stop.ps1`, `cli.ps1`
- Docker Desktop or compatible Docker Compose runtime
- Worker image built from `docker/worker.Dockerfile`

The normal command path is PowerShell to Docker Compose to the Python worker.

## Docker Resources

```text
app-data     Internal runtime state
cache-data   OCR and future model cache
C:\ bind     Local Windows path access inside the container
```

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
