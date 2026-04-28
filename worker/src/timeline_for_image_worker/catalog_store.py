from __future__ import annotations

from pathlib import Path
from typing import Any

from .captioning import resolve_caption_model
from .contracts import ImageItem
from .fs_utils import now_iso, read_json, write_json
from .ocr import resolve_ocr_model

CATALOG_VERSION = 1
PROCESSING_PROFILE = "metadata-v2"


def build_processing_profile(
    caption_mode: str,
    caption_model: str | None,
    ocr_mode: str = "auto",
    ocr_model: str | None = None,
) -> str:
    if caption_mode == "off":
        caption_profile = "caption-off"
    else:
        caption_profile = f"caption-{caption_mode}-{resolve_caption_model(caption_mode, caption_model) or 'none'}"
    ocr_profile = f"ocr-{ocr_mode}-{resolve_ocr_model(ocr_mode, ocr_model) or 'none'}"
    if caption_mode == "off" and ocr_mode == "off":
        return PROCESSING_PROFILE
    return f"{PROCESSING_PROFILE}+{caption_profile}+{ocr_profile}"


def master_catalog_path(state_root: Path) -> Path:
    return state_root / "master_catalog.json"


def load_master_catalog(state_root: Path) -> dict[str, Any]:
    path = master_catalog_path(state_root)
    if not path.exists():
        return {"version": CATALOG_VERSION, "processing_profile": PROCESSING_PROFILE, "items": {}}
    payload = read_json(path)
    if not isinstance(payload.get("items"), dict):
        raise ValueError("master_catalog.json is invalid: items must be an object.")
    return payload


def compare_items(state_root: Path, items: list[ImageItem], processing_profile: str = PROCESSING_PROFILE) -> dict[str, int]:
    catalog = load_master_catalog(state_root)
    existing = catalog.get("items", {})
    summary = {"new": 0, "changed": 0, "unchanged": 0}
    for item in items:
        previous = existing.get(item.source_path)
        signature = _item_signature(item, processing_profile)
        if previous is None:
            summary["new"] += 1
        elif previous.get("signature") == signature:
            summary["unchanged"] += 1
        else:
            summary["changed"] += 1
    return summary


def update_master_catalog(state_root: Path, items: list[ImageItem], processing_profile: str = PROCESSING_PROFILE) -> None:
    catalog = load_master_catalog(state_root)
    existing = catalog.get("items", {})
    for item in items:
        existing[item.source_path] = {
            "signature": _item_signature(item, processing_profile),
            "relative_path": item.relative_path,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "modified_at": item.modified_at,
            "timeline_at": item.timeline_at,
            "camera_make": item.camera_make,
            "camera_model": item.camera_model,
            "lens_model": item.lens_model,
            "focal_length_mm": item.focal_length_mm,
            "gps_latitude": item.gps_latitude,
            "gps_longitude": item.gps_longitude,
            "gps_altitude_m": item.gps_altitude_m,
            "processing_profile": processing_profile,
            "last_seen_at": now_iso(),
        }
    catalog["version"] = CATALOG_VERSION
    catalog["processing_profile"] = processing_profile
    catalog["updated_at"] = now_iso()
    catalog["items"] = existing
    write_json(master_catalog_path(state_root), catalog)


def _item_signature(item: ImageItem, processing_profile: str) -> str:
    return "|".join([processing_profile, item.sha256, str(item.size_bytes), item.modified_at])
