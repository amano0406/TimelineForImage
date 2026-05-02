from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps, ImageStat

from .contracts import ImageSource
from .fs_utils import now_iso

SCHEMA_VERSION = "timeline_for_image.image_record.v1"


def build_image_record(item: ImageSource, ocr: dict[str, Any]) -> dict[str, Any]:
    features = read_image_features(Path(item.source_path))
    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": item.item_id,
        "asset": {
            "source_path": item.source_path,
            "relative_path": item.relative_path,
            "media_type": "image",
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "format_name": item.format_name,
        },
        "timeline": {
            "timeline_at": item.captured_at or item.modified_at,
            "captured_at": item.captured_at,
            "modified_at": item.modified_at,
        },
        "image": {
            "width": item.width,
            "height": item.height,
            "orientation": orientation(item.width, item.height),
            "camera": {
                "make": item.camera_make,
                "model": item.camera_model,
            },
        },
        "processing": {
            "profile": "timeline_for_image_local_v1",
            "generated_at": now_iso(),
            "context_policy": "single_image_only",
            "privacy_filter": "none",
            "source_image_modified": False,
        },
        "quality": features["quality"],
        "classification": {
            "image_kind": image_kind(item, ocr),
            "content_types": content_types(ocr),
        },
        "text": {
            "has_text": bool(ocr.get("has_text")),
            "full_text": ocr.get("full_text", ""),
            "blocks": normalized_ocr_blocks(ocr),
        },
        "visual": {
            "caption": "",
            "scene_summary": "",
            "observations": [],
        },
        "layout": {
            "coordinate_system": "normalized_xyxy",
            "color_palette": features["color_palette"],
            "grid": features["grid"],
            "text_regions": [
                {
                    "block_id": block["block_id"],
                    "text": block["text"],
                    "bbox_norm": block["bbox_norm"],
                    "z_index": 20,
                }
                for block in normalized_ocr_blocks(ocr)
            ],
            "spatial_relations": spatial_relations(ocr),
        },
        "search": {
            "keywords": search_keywords(item, ocr),
        },
        "review": {
            "needs_review": bool(item.warnings or ocr.get("warnings")),
            "warnings": [*item.warnings, *ocr.get("warnings", [])],
        },
    }


def read_image_features(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            return {
                "quality": quality(image),
                "color_palette": color_palette(image),
                "grid": color_grid(image),
            }
    except Exception as exc:
        return {
            "quality": {"brightness": None, "contrast": None, "warnings": [f"feature extraction failed: {exc}"]},
            "color_palette": [],
            "grid": [],
        }


def quality(image: Image.Image) -> dict[str, Any]:
    gray = image.convert("L")
    stat = ImageStat.Stat(gray)
    brightness = float(stat.mean[0])
    contrast = float(stat.stddev[0])
    return {
        "brightness": round(brightness, 3),
        "contrast": round(contrast, 3),
        "brightness_level": "dark" if brightness < 55 else "bright" if brightness > 205 else "normal",
        "contrast_level": "low" if contrast < 20 else "high" if contrast > 70 else "normal",
        "warnings": [],
    }


def color_palette(image: Image.Image, limit: int = 8) -> list[dict[str, Any]]:
    sample = image.copy()
    sample.thumbnail((160, 160))
    quantized = sample.quantize(colors=limit, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette() or []
    colors = quantized.getcolors(sample.width * sample.height) or []
    total = float(sample.width * sample.height) or 1.0
    result = []
    for count, index in sorted(colors, reverse=True):
        offset = index * 3
        if offset + 2 >= len(palette):
            continue
        rgb = tuple(int(value) for value in palette[offset : offset + 3])
        result.append({"hex": hex_color(rgb), "rgb": list(rgb), "ratio": round(count / total, 4)})
    return result


def color_grid(image: Image.Image, rows: int = 3, cols: int = 3) -> list[dict[str, Any]]:
    width, height = image.size
    cells = []
    for row in range(rows):
        for col in range(cols):
            left = col / cols
            top = row / rows
            right = (col + 1) / cols
            bottom = (row + 1) / rows
            crop = image.crop((int(left * width), int(top * height), int(right * width), int(bottom * height)))
            rgb = tuple(int(round(value)) for value in ImageStat.Stat(crop).mean[:3])
            cells.append(
                {
                    "cell_id": f"grid_{row}_{col}",
                    "row": row,
                    "col": col,
                    "bbox_norm": [round(left, 6), round(top, 6), round(right, 6), round(bottom, 6)],
                    "average_color": {"hex": hex_color(rgb), "rgb": list(rgb)},
                }
            )
    return cells


def save_normalized_image(source: Path, target: Path, max_side: int = 1600) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        image.thumbnail((max_side, max_side))
        image.save(target, "JPEG", quality=90)


def save_debug_overlay(source: Path, target: Path, ocr: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        draw = ImageDraw.Draw(image)
        width, height = image.size
        for block in normalized_ocr_blocks(ocr):
            left, top, right, bottom = block["bbox_norm"]
            box = [left * width, top * height, right * width, bottom * height]
            draw.rectangle(box, outline=(255, 196, 0), width=max(2, width // 400))
        image.thumbnail((1600, 1600))
        image.save(target, "JPEG", quality=90)


def normalized_ocr_blocks(ocr: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []
    for index, raw in enumerate(ocr.get("blocks", [])):
        text = str(raw.get("text") or "").strip()
        bbox = raw.get("bbox_norm")
        if not text or not isinstance(bbox, list) or len(bbox) != 4:
            continue
        blocks.append(
            {
                "block_id": str(raw.get("block_id") or f"ocr_{index + 1:04d}"),
                "text": text,
                "normalized_text": text,
                "role": "unknown",
                "bbox_norm": [round(float(value), 6) for value in bbox],
                "confidence": raw.get("confidence") or {"score": None, "level": "unknown"},
                "evidence": {"channel": "ocr", "stage": "ocr"},
            }
        )
    return blocks


def orientation(width: int | None, height: int | None) -> str:
    if not width or not height:
        return "unknown"
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def image_kind(item: ImageSource, ocr: dict[str, Any]) -> str:
    if ocr.get("has_text") and item.width and item.height and item.height > item.width * 1.2:
        return "document_or_screenshot"
    if ocr.get("has_text"):
        return "photo_with_text"
    return "photo"


def content_types(ocr: dict[str, Any]) -> list[str]:
    values = {"image"}
    if ocr.get("has_text"):
        values.add("text")
    return sorted(values)


def spatial_relations(ocr: dict[str, Any]) -> list[dict[str, Any]]:
    if not normalized_ocr_blocks(ocr):
        return []
    return [
        {
            "type": "text_overlay",
            "subject": "ocr_text",
            "object": "image",
            "relation": "located_on_image",
            "certainty": "observed",
        }
    ]


def search_keywords(item: ImageSource, ocr: dict[str, Any]) -> list[str]:
    values = {item.relative_path, item.format_name.lower()}
    for part in str(ocr.get("full_text") or "").replace("\n", " ").split():
        if len(part) >= 2:
            values.add(part)
    return sorted(values)


def hex_color(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)
