from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import CaptionRecord, ImageItem, OcrRecord, VisualObservationRecord
from .fs_utils import now_iso, read_json, write_json

CACHE_VERSION = 1


def load_derived_cache(state_root: Path | None) -> tuple[dict[str, Any], list[str]]:
    if state_root is None:
        return _empty_cache(), []
    path = derived_cache_path(state_root)
    if not path.exists():
        return _empty_cache(), []
    try:
        payload = read_json(path)
    except Exception as exc:
        return _empty_cache(), [f"derived cache could not be read; cache ignored: {exc}"]
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), dict):
        return _empty_cache(), ["derived cache was invalid; cache ignored"]
    payload["version"] = CACHE_VERSION
    return payload, []


def save_derived_cache(state_root: Path | None, cache: dict[str, Any]) -> None:
    if state_root is None:
        return
    cache["version"] = CACHE_VERSION
    cache["updated_at"] = now_iso()
    write_json(derived_cache_path(state_root), cache)


def derived_cache_path(state_root: Path) -> Path:
    return state_root / "derived_cache.json"


def cache_key(item: ImageItem, processing_profile: str) -> str:
    return f"{processing_profile}|sha256:{item.sha256}"


def restore_derivatives(
    cache: dict[str, Any],
    item: ImageItem,
    processing_profile: str,
) -> tuple[CaptionRecord | None, OcrRecord | None, VisualObservationRecord | None] | None:
    raw_record = cache.get("records", {}).get(cache_key(item, processing_profile))
    if not isinstance(raw_record, dict):
        return None
    if raw_record.get("sha256") != item.sha256 or raw_record.get("processing_profile") != processing_profile:
        return None
    raw_observation = raw_record.get("visual_observation")
    if not isinstance(raw_observation, dict):
        return None
    try:
        caption = _restore_caption(item, raw_record.get("caption"))
        ocr = _restore_ocr(item, raw_record.get("ocr"))
        observation = VisualObservationRecord(**{**raw_observation, "source_path": item.source_path})
    except (TypeError, ValueError):
        return None
    return caption, ocr, observation


def store_derivatives(
    cache: dict[str, Any],
    item: ImageItem,
    processing_profile: str,
    caption: CaptionRecord | None,
    ocr: OcrRecord | None,
    observation: VisualObservationRecord,
) -> None:
    records = cache.setdefault("records", {})
    records[cache_key(item, processing_profile)] = {
        "sha256": item.sha256,
        "processing_profile": processing_profile,
        "updated_at": now_iso(),
        "caption": caption.to_dict() if caption is not None else None,
        "ocr": ocr.to_dict() if ocr is not None else None,
        "visual_observation": observation.to_dict(),
    }


def _empty_cache() -> dict[str, Any]:
    return {"version": CACHE_VERSION, "records": {}}


def _restore_caption(item: ImageItem, raw: Any) -> CaptionRecord | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("cached caption is invalid")
    return CaptionRecord(**{**raw, "source_path": item.source_path})


def _restore_ocr(item: ImageItem, raw: Any) -> OcrRecord | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("cached OCR is invalid")
    return OcrRecord(**{**raw, "source_path": item.source_path})
