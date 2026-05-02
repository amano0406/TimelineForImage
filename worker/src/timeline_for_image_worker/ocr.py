from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


def run_ocr(image_path: Path, mode: str) -> dict[str, Any]:
    if mode == "off":
        return {"mode": mode, "model": None, "has_text": False, "full_text": "", "blocks": [], "warnings": []}
    if mode == "mock":
        text = f"Mock OCR for {image_path.name}"
        return {
            "mode": mode,
            "model": None,
            "has_text": True,
            "full_text": text,
            "blocks": [
                {
                    "block_id": "ocr_0001",
                    "text": text,
                    "bbox_norm": [0.05, 0.05, 0.95, 0.15],
                    "confidence": {"score": None, "level": "unknown"},
                }
            ],
            "warnings": ["mock OCR; image text was not inspected"],
        }
    return _run_tesseract(image_path, mode)


def _run_tesseract(image_path: Path, mode: str) -> dict[str, Any]:
    try:
        import pytesseract
        from pytesseract import Output

        with Image.open(image_path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            full_text = pytesseract.image_to_string(image, lang="jpn+eng").strip()
            data = pytesseract.image_to_data(image, lang="jpn+eng", output_type=Output.DICT)
            blocks = _blocks_from_tesseract(data, image.size)
        return {
            "mode": mode,
            "model": "tesseract:jpn+eng",
            "has_text": bool(full_text or blocks),
            "full_text": full_text,
            "blocks": blocks,
            "warnings": [],
        }
    except Exception as exc:
        if mode == "auto":
            return {
                "mode": mode,
                "model": "tesseract:jpn+eng",
                "has_text": False,
                "full_text": "",
                "blocks": [],
                "warnings": [f"OCR failed in auto mode: {exc}"],
            }
        raise


def _blocks_from_tesseract(data: dict[str, list[Any]], size: tuple[int, int]) -> list[dict[str, Any]]:
    width, height = size
    blocks: list[dict[str, Any]] = []
    count = len(data.get("text", []))
    for index in range(count):
        text = str(data["text"][index] or "").strip()
        if not text:
            continue
        conf = _confidence(data.get("conf", ["-1"])[index])
        if conf is not None and conf < 0:
            continue
        left = float(data.get("left", [0])[index])
        top = float(data.get("top", [0])[index])
        box_width = float(data.get("width", [0])[index])
        box_height = float(data.get("height", [0])[index])
        blocks.append(
            {
                "block_id": f"ocr_{len(blocks) + 1:04d}",
                "text": text,
                "bbox_norm": _norm_bbox(left, top, left + box_width, top + box_height, width, height),
                "confidence": {"score": conf, "level": _confidence_level(conf)},
            }
        )
    return blocks


def _confidence(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed > 1:
        parsed /= 100.0
    return round(parsed, 4)


def _confidence_level(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 0.85:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def _norm_bbox(left: float, top: float, right: float, bottom: float, width: int, height: int) -> list[float]:
    if width <= 0 or height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(max(0.0, min(1.0, left / width)), 6),
        round(max(0.0, min(1.0, top / height)), 6),
        round(max(0.0, min(1.0, right / width)), 6),
        round(max(0.0, min(1.0, bottom / height)), 6),
    ]
