# Outputs

[Back to README](../README.md)

TimelineForImage writes structured records under the configured `outputRoot`.

## Output Tree

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

## Main Record

`image_record.json` is the primary artifact for each image.

Important top-level keys:

```text
schema_version
record_id
asset
timeline
image
processing
quality
classification
text
visual
layout
search
review
```

The machine-readable schema is stored at:

```text
schemas/image_record.schema.json
```

## Timeline Record

`timeline.json` is the Timeline-facing record for a single image observation. It references the image record and includes the event time derived from captured time when available, otherwise file modified time.

## Convert Info

`convert_info.json` describes the conversion profile, source metadata, and relative output paths for the generated artifacts.

## Raw Outputs

`raw_outputs/ocr.json` stores the raw local OCR result used to build the text fields and text regions.

## Artifacts

`artifacts/normalized_image.jpg` is a normalized JPEG copy for downstream inspection. `artifacts/debug_overlay.jpg` shows OCR regions over the image.

## Download ZIPs

Download ZIPs include generated JSON records and README metadata. They do not include original source image files.
