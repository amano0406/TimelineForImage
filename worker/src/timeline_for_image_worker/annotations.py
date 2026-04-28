from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import HumanAnnotationRecord, ImageItem
from .fs_utils import read_json


def load_human_annotations(items: list[ImageItem], annotation_path: str | None) -> list[HumanAnnotationRecord]:
    if not annotation_path:
        return []
    path = Path(annotation_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Annotation file not found: {path}")
    payload = read_json(path)
    if isinstance(payload, list):
        raw_annotations = payload
    elif isinstance(payload, dict):
        raw_annotations = payload.get("annotations", [])
    else:
        raw_annotations = []
    if not isinstance(raw_annotations, list):
        raise ValueError("Annotation file must be a list or an object with an annotations list.")
    item_paths = {item.source_path for item in items}
    item_relative_paths = {item.relative_path: item.source_path for item in items}
    records: list[HumanAnnotationRecord] = []
    for raw in raw_annotations:
        if not isinstance(raw, dict):
            raise ValueError("Each annotation must be an object.")
        source_path = _resolve_source_path(raw, item_paths, item_relative_paths)
        if source_path is None:
            continue
        records.append(
            HumanAnnotationRecord(
                source_path=source_path,
                tags=_string_list(raw.get("tags")),
                people=_string_list(raw.get("people")),
                event=_optional_string(raw.get("event")),
                note=_optional_string(raw.get("note")),
            )
        )
    return records


def _resolve_source_path(raw: dict[str, Any], item_paths: set[str], item_relative_paths: dict[str, str]) -> str | None:
    source_path = _optional_string(raw.get("source_path"))
    if source_path in item_paths:
        return source_path
    relative_path = _optional_string(raw.get("relative_path"))
    if relative_path and relative_path in item_relative_paths:
        return item_relative_paths[relative_path]
    return None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Annotation tags and people must be lists.")
    return [str(item) for item in value if str(item)]


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
