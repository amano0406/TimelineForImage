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


SETTINGS_SCHEMA_VERSION = 1
SETTINGS_KEYS = ("schemaVersion", "inputRoots", "outputRoot")
INTERNAL_STATE_ROOT = "/shared/app-data/timeline-for-image-state"


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
    unknown = sorted(set(payload) - set(SETTINGS_KEYS))
    if unknown:
        raise ValueError(f"settings.json has unsupported keys: {', '.join(unknown)}")
    missing = [key for key in SETTINGS_KEYS if key not in payload]
    if missing:
        raise ValueError(f"settings.json is missing required keys: {', '.join(missing)}")
    schema_version = int(payload["schemaVersion"])
    if schema_version != SETTINGS_SCHEMA_VERSION:
        raise ValueError(f"Unsupported schemaVersion: {schema_version}")
    if not isinstance(payload["inputRoots"], list):
        raise ValueError("inputRoots must be an array.")
    input_roots = normalize_path_list(payload["inputRoots"], "inputRoots")
    output_root = normalize_path_string(payload["outputRoot"], "outputRoot")
    return Settings(
        schema_version=schema_version,
        input_roots=input_roots,
        output_root=output_root,
    )


def save_settings(settings: Settings) -> None:
    write_json(settings_path(), settings_to_payload(settings))


def settings_to_payload(settings: Settings) -> dict[str, Any]:
    return {
        "schemaVersion": settings.schema_version,
        "inputRoots": settings.input_roots,
        "outputRoot": settings.output_root,
    }


def default_settings_payload() -> dict[str, Any]:
    return {
        "schemaVersion": SETTINGS_SCHEMA_VERSION,
        "inputRoots": ["C:\\TimelineData\\input-image\\"],
        "outputRoot": "C:\\TimelineData\\image",
    }


def normalize_path_list(values: list[Any], key: str) -> list[str]:
    paths = [normalize_path_string(value, f"{key}[{index}]") for index, value in enumerate(values)]
    if not paths:
        raise ValueError(f"{key} must contain at least one path.")
    return paths


def normalize_path_string(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{key} must not be empty.")
    return normalized


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


def internal_state_root() -> Path:
    return Path(os.environ.get("TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT", INTERNAL_STATE_ROOT)).expanduser().resolve()
