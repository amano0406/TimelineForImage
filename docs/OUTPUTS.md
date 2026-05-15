# Outputs

[Back to README](../README.md)

TimelineForImage writes structured records under the configured `outputRoot`.
The generated records are intended for downstream Timeline, search, handoff,
and LLM workflows. Original source image files are never copied into download
ZIPs.

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

`<item-id>` is stable for a source image and currently has the form
`image-<16 hex chars>`, for example `image-c15d1645b6ce4244`.

## Main Record

`image_record.json` is the primary per-image record. It combines source file
metadata, timeline timestamps, local image features, OCR text, layout regions,
search keywords, and review warnings.

The machine-readable schema is stored at:

```text
schemas/image_record.schema.json
```

Representative shape:

```json
{
  "schema_version": "timeline_for_image.image_record.v1",
  "record_id": "image-c15d1645b6ce4244",
  "asset": {
    "source_path": "/mnt/c/apps/Timeline/data/input/image/sample.png",
    "relative_path": "sample.png",
    "media_type": "image",
    "sha256": "3afeb0937aad9be465c0135ef6ae5bd3ad6213e672b6ac1b6b145eadf6684cdd",
    "size_bytes": 85297,
    "format_name": "PNG"
  },
  "timeline": {
    "timeline_at": "2026-05-13T01:05:15+00:00",
    "captured_at": null,
    "modified_at": "2026-05-13T01:05:15+00:00"
  },
  "image": {
    "width": 1920,
    "height": 1080,
    "orientation": "landscape",
    "camera": {
      "make": null,
      "model": null
    }
  },
  "processing": {
    "profile": "timeline_for_image_local_v1",
    "generated_at": "2026-05-13T19:45:00+00:00",
    "context_policy": "single_image_only",
    "source_image_modified": false
  },
  "quality": {
    "brightness": 142.381,
    "contrast": 51.207,
    "brightness_level": "normal",
    "contrast_level": "normal",
    "warnings": []
  },
  "classification": {
    "image_kind": "photo_with_text",
    "content_types": ["image", "text"]
  },
  "text": {
    "has_text": true,
    "full_text": "Example OCR text",
    "blocks": [
      {
        "block_id": "ocr_0001",
        "text": "Example OCR text",
        "normalized_text": "Example OCR text",
        "role": "unknown",
        "bbox_norm": [0.05, 0.05, 0.95, 0.15],
        "confidence": {
          "score": 0.9123,
          "level": "high"
        },
        "evidence": {
          "channel": "ocr",
          "stage": "ocr"
        }
      }
    ]
  },
  "visual": {
    "caption": "",
    "scene_summary": "",
    "observations": []
  },
  "layout": {
    "coordinate_system": "normalized_xyxy",
    "color_palette": [
      {
        "hex": "#f8f8f8",
        "rgb": [248, 248, 248],
        "ratio": 0.62
      }
    ],
    "grid": [
      {
        "cell_id": "grid_0_0",
        "row": 0,
        "col": 0,
        "bbox_norm": [0.0, 0.0, 0.333333, 0.333333],
        "average_color": {
          "hex": "#ffffff",
          "rgb": [255, 255, 255]
        }
      }
    ],
    "text_regions": [
      {
        "block_id": "ocr_0001",
        "text": "Example OCR text",
        "bbox_norm": [0.05, 0.05, 0.95, 0.15],
        "z_index": 20
      }
    ],
    "spatial_relations": [
      {
        "type": "text_overlay",
        "subject": "ocr_text",
        "object": "image",
        "relation": "located_on_image",
        "certainty": "observed"
      }
    ]
  },
  "search": {
    "keywords": ["Example", "OCR", "PNG", "sample.png", "text"]
  },
  "review": {
    "needs_review": false,
    "warnings": []
  }
}
```

## Main Record Fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Record contract version. Current value is `timeline_for_image.image_record.v1`. |
| `record_id` | Stable image item id used as the output directory name. |
| `asset` | Source file path, relative path, media type, checksum, file size, and image format. |
| `timeline` | Timeline timestamp. `captured_at` is used when available; otherwise `modified_at` is used. |
| `image` | Pixel dimensions, orientation, and camera metadata when available. |
| `processing` | Local processing profile, generation time, and source mutation policy. |
| `quality` | Brightness, contrast, derived quality labels, and feature extraction warnings. |
| `classification` | Current image kind and broad content types derived from local signals. |
| `text` | OCR summary text and normalized OCR text blocks. |
| `visual` | Reserved visual description fields. Current local worker leaves these empty. |
| `layout` | Normalized coordinate system, colors, grid cells, OCR regions, and spatial relations. |
| `search` | Keywords derived from filename, format, and OCR text. |
| `review` | Whether downstream review is recommended and why. |

## Timeline Record

`timeline.json` is a compact Timeline-facing record for a single image
observation. It references `image_record.json` and summarizes the event.

```json
{
  "schema_version": 1,
  "artifact_type": "image_timeline",
  "item_id": "image-c15d1645b6ce4244",
  "source": {
    "path": "/mnt/c/apps/Timeline/data/input/image/sample.png",
    "relative_path": "sample.png",
    "sha256": "3afeb0937aad9be465c0135ef6ae5bd3ad6213e672b6ac1b6b145eadf6684cdd"
  },
  "events": [
    {
      "time": "2026-05-13T01:05:15+00:00",
      "type": "image_observed",
      "image_record_ref": "image_record.json",
      "summary": {
        "image_kind": "photo_with_text",
        "content_types": ["image", "text"],
        "has_text": true,
        "ocr_block_count": 1
      }
    }
  ]
}
```

## Convert Info

`convert_info.json` records how the item was converted and where the generated
files are located relative to the item directory.

```json
{
  "schema_version": 1,
  "product": "TimelineForImage",
  "item_id": "image-c15d1645b6ce4244",
  "source": {
    "item_id": "image-c15d1645b6ce4244",
    "source_path": "/mnt/c/apps/Timeline/data/input/image/sample.png",
    "relative_path": "sample.png",
    "display_name": "sample.png",
    "sha256": "3afeb0937aad9be465c0135ef6ae5bd3ad6213e672b6ac1b6b145eadf6684cdd",
    "size_bytes": 85297,
    "modified_at": "2026-05-13T01:05:15+00:00",
    "format_name": "PNG",
    "width": 1920,
    "height": 1080,
    "captured_at": null,
    "camera_make": null,
    "camera_model": null,
    "warnings": []
  },
  "pipeline": {
    "version": "timeline-for-image-local-v1",
    "source_image_modified": false
  },
  "outputs": {
    "image_record": "image_record.json",
    "timeline": "timeline.json",
    "ocr": "raw_outputs/ocr.json",
    "normalized_image": "artifacts/normalized_image.jpg",
    "debug_overlay": "artifacts/debug_overlay.jpg"
  }
}
```

## Raw OCR Output

`raw_outputs/ocr.json` stores the OCR result before it is normalized into
`image_record.json`.

```json
{
  "mode": "auto",
  "model": "tesseract:jpn+eng",
  "has_text": true,
  "full_text": "Example OCR text",
  "blocks": [
    {
      "block_id": "ocr_0001",
      "text": "Example OCR text",
      "bbox_norm": [0.05, 0.05, 0.95, 0.15],
      "confidence": {
        "score": 0.9123,
        "level": "high"
      }
    }
  ],
  "warnings": []
}
```

If OCR fails in `auto` mode, the worker still writes a valid record with
`has_text: false`, an empty `full_text`, no OCR blocks, and a warning.

## Image Artifacts

`artifacts/normalized_image.jpg` is a JPEG copy normalized for downstream
inspection. It is not a replacement for the source file.

`artifacts/debug_overlay.jpg` is a JPEG with OCR regions drawn over the image.
It is useful for checking whether text regions were detected where expected.

## Download ZIPs

`items download` creates `TimelineForImage-selected.zip`. A refresh that
processed images creates timestamped export ZIPs such as
`TimelineForImage-export-<timestamp>-<id>.zip`; the latest generated export is
also copied to `latest/TimelineForImage-export.zip`.

ZIP contents include generated records only:

```text
README.md
items/<item-id>/convert_info.json
items/<item-id>/timeline.json
items/<item-id>/image_record.json
```

Original source image files are not included in ZIP exports.

## Internal State Is Separate

The internal catalog, operation locks, and run status files live under the
internal state root, not under `outputRoot`. They support CLI operations such as
`items list`, `runs list`, and `runs show`, but they are not the handoff output
contract for downstream consumers.
