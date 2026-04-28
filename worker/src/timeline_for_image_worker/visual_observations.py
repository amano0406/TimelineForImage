from __future__ import annotations

import re

from .contracts import CaptionRecord, ImageItem, OcrRecord, VisualObservationRecord

OBJECT_KEYWORDS = {
    "card": "card",
    "sign": "sign",
    "text": "text",
    "photo": "photo",
    "frame": "frame",
    "building": "building",
    "car": "car",
    "food": "food",
    "table": "table",
    "screen": "screen",
    "document": "document",
    "person": "person",
    "people": "person",
    "dog": "animal",
    "cat": "animal",
}

ACTIVITY_KEYWORDS = {
    "walking": "walking",
    "running": "running",
    "eating": "eating",
    "sitting": "sitting",
    "standing": "standing",
    "driving": "driving",
    "playing": "playing",
}

PLACE_KEYWORDS = {
    "street": "street/outdoor",
    "road": "street/outdoor",
    "park": "park/outdoor",
    "room": "indoor",
    "kitchen": "kitchen/indoor",
    "office": "office/indoor",
    "restaurant": "restaurant/indoor",
    "beach": "beach/outdoor",
}


def build_visual_observations(
    items: list[ImageItem],
    captions_by_path: dict[str, CaptionRecord],
    ocr_by_path: dict[str, OcrRecord],
) -> list[VisualObservationRecord]:
    return [_build_record(item, captions_by_path.get(item.source_path), ocr_by_path.get(item.source_path)) for item in items]


def _build_record(item: ImageItem, caption: CaptionRecord | None, ocr: OcrRecord | None) -> VisualObservationRecord:
    caption_text = caption.text if caption else ""
    ocr_text = ocr.text if ocr else ""
    combined = " ".join(part for part in [caption_text, ocr_text] if part).lower()
    objects = sorted({label for keyword, label in OBJECT_KEYWORDS.items() if keyword in combined})
    activities = sorted({label for keyword, label in ACTIVITY_KEYWORDS.items() if keyword in combined})
    place_hint = next((label for keyword, label in PLACE_KEYWORDS.items() if keyword in combined), None)
    has_text = bool(ocr_text.strip()) or "text" in combined or _looks_like_text_heavy(caption_text)
    has_people = _infer_people(caption_text)
    warnings: list[str] = []
    if caption is None:
        warnings.append("caption unavailable; visual observations are metadata/OCR only")
    elif caption.warnings:
        warnings.append("caption has warnings; observations may be incomplete")
    return VisualObservationRecord(
        source_path=item.source_path,
        has_people=has_people,
        has_text=has_text,
        place_hint=place_hint,
        activities=activities,
        objects=objects,
        scene_summary=caption_text,
        warnings=warnings,
    )


def _infer_people(caption_text: str) -> bool | None:
    normalized = caption_text.lower()
    if any(word in normalized for word in ["person", "people", "man", "woman", "child", "boy", "girl"]):
        return True
    if caption_text:
        return False
    return None


def _looks_like_text_heavy(text: str) -> bool:
    return bool(re.search(r"\b(text|words|sign|document|label|caption)\b", text.lower()))
