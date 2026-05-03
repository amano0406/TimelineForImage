from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .contracts import ImageSource
from .fs_utils import read_json, write_json

PIPELINE_VERSION = "timeline-for-image-local-v1"


def catalog_path(state_root: Path) -> Path:
    return state_root / "catalog.json"


def load_catalog(state_root: Path) -> dict[str, Any]:
    path = catalog_path(state_root)
    if not path.exists():
        return {"schema_version": 1, "pipeline_version": PIPELINE_VERSION, "items": {}}
    payload = read_json(path)
    if not isinstance(payload.get("items"), dict):
        return {"schema_version": 1, "pipeline_version": PIPELINE_VERSION, "items": {}}
    return payload


def save_catalog(state_root: Path, catalog: dict[str, Any]) -> None:
    catalog["schema_version"] = 1
    catalog["pipeline_version"] = PIPELINE_VERSION
    write_json(catalog_path(state_root), catalog)


def source_signature(item: ImageSource) -> str:
    raw = "|".join([PIPELINE_VERSION, item.sha256, str(item.size_bytes), item.modified_at])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def needs_processing(catalog: dict[str, Any], item: ImageSource, reprocess_duplicates: bool) -> bool:
    if reprocess_duplicates:
        return True
    previous = catalog.get("items", {}).get(item.item_id)
    return not previous or previous.get("signature") != source_signature(item)


def update_catalog_item(catalog: dict[str, Any], item: ImageSource, output_dir: Path) -> None:
    records = catalog.setdefault("items", {})
    records[item.item_id] = {
        "item_id": item.item_id,
        "source_path": item.source_path,
        "relative_path": item.relative_path,
        "sha256": item.sha256,
        "size_bytes": item.size_bytes,
        "modified_at": item.modified_at,
        "signature": source_signature(item),
        "output_dir": str(output_dir),
    }


def remove_catalog_item(catalog: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    records = catalog.setdefault("items", {})
    removed = records.pop(item_id, None)
    return removed if isinstance(removed, dict) else None
