from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fs_utils import read_json, write_json


@dataclass(frozen=True)
class Settings:
    schema_version: int
    input_roots: list[str]
    output_root: str
    appdata_root: str
    compute_mode: str
    ocr_mode: str
    privacy_filter: str


def settings_path() -> Path:
    return Path(os.environ.get("TIMELINE_FOR_IMAGE_SETTINGS_PATH", "/workspace/settings.json"))


def settings_example_path() -> Path:
    return Path(os.environ.get("TIMELINE_FOR_IMAGE_SETTINGS_EXAMPLE_PATH", "/workspace/settings.example.json"))


def init_settings() -> tuple[bool, Path]:
    path = settings_path()
    if path.exists():
        return False, path
    path.parent.mkdir(parents=True, exist_ok=True)
    example = settings_example_path()
    if example.exists():
        shutil.copyfile(example, path)
    else:
        write_json(path, default_settings_payload())
    return True, path


def load_settings() -> Settings:
    if not settings_path().exists():
        init_settings()
    payload = read_json(settings_path())
    return Settings(
        schema_version=int(payload.get("schemaVersion") or payload.get("schema_version") or 1),
        input_roots=[str(value) for value in payload.get("inputRoots", [])],
        output_root=str(payload.get("outputRoot") or "C:\\TimelineData\\image"),
        appdata_root=str(payload.get("appdataRoot") or "C:\\TimelineData\\image\\.timeline-for-image-state"),
        compute_mode=str(payload.get("computeMode") or "cpu"),
        ocr_mode=str(payload.get("ocrMode") or "auto"),
        privacy_filter=str(payload.get("privacyFilter") or "none"),
    )


def save_settings(settings: Settings) -> None:
    write_json(settings_path(), settings_to_payload(settings))


def settings_to_payload(settings: Settings) -> dict[str, Any]:
    return {
        "schemaVersion": settings.schema_version,
        "inputRoots": settings.input_roots,
        "outputRoot": settings.output_root,
        "appdataRoot": settings.appdata_root,
        "computeMode": settings.compute_mode,
        "ocrMode": settings.ocr_mode,
        "privacyFilter": settings.privacy_filter,
    }


def default_settings_payload() -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "inputRoots": ["C:\\TimelineData\\input-image\\"],
        "outputRoot": "C:\\TimelineData\\image",
        "appdataRoot": "C:\\TimelineData\\image\\.timeline-for-image-state",
        "computeMode": "cpu",
        "ocrMode": "auto",
        "privacyFilter": "none",
    }


def resolve_local_path(value: str) -> Path:
    normalized = value.strip()
    match = re.match(r"^([A-Za-z]):[\\/]*(.*)$", normalized)
    if match:
        drive = match.group(1).lower()
        rest = match.group(2).replace("\\", "/")
        return Path("/mnt") / drive / rest
    return Path(normalized).expanduser()


def resolved_input_roots(settings: Settings) -> list[Path]:
    return [resolve_local_path(value).resolve() for value in settings.input_roots]


def resolved_output_root(settings: Settings) -> Path:
    return resolve_local_path(settings.output_root).resolve()


def resolved_appdata_root(settings: Settings) -> Path:
    return resolve_local_path(settings.appdata_root).resolve()
