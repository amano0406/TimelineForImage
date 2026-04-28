from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .config import load_config
from .contracts import RuntimePaths
from .fs_utils import read_json, write_json

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SETTINGS_ENV = "TIMELINE_FOR_IMAGE_SETTINGS_PATH"
SETTINGS_EXAMPLE_ENV = "TIMELINE_FOR_IMAGE_SETTINGS_EXAMPLE_PATH"


def settings_path() -> Path:
    override = os.environ.get(SETTINGS_ENV)
    if override:
        return path_from_user_value(override)
    return PROJECT_ROOT / "settings.json"


def settings_example_path(settings_file: Path | None = None) -> Path:
    override = os.environ.get(SETTINGS_EXAMPLE_ENV)
    if override:
        return path_from_user_value(override)
    if settings_file is not None:
        sibling = settings_file.parent / "settings.example.json"
        if sibling.exists():
            return sibling
    return PROJECT_ROOT / "settings.example.json"


def load_settings() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {}
    return load_config(str(path))


def init_settings() -> tuple[bool, Path]:
    target = settings_path()
    if target.exists():
        return False, target
    example = settings_example_path(target)
    payload = read_json(example) if example.exists() else default_settings()
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, payload)
    return True, target


def default_settings() -> dict[str, Any]:
    return {
        "sources": [
            {
                "path": "C:\\Users\\amano\\Pictures\\",
                "recursive": True,
            }
        ],
        "outputs_root": "C:\\Users\\amano\\image\\",
        "appdata_root": "C:\\Users\\amano\\image\\.timeline-for-image-state",
        "caption": {
            "mode": "local",
            "model": "Salesforce/blip-image-captioning-base",
        },
        "ocr": {
            "mode": "auto",
            "model": "tesseract:eng+jpn",
        },
        "watch": {
            "interval_seconds": 30,
            "min_quiet_seconds": 2,
        },
        "mock": False,
    }


def normalize_local_path(value: str) -> str:
    if os.name == "nt":
        return value
    match = re.match(r"^([A-Za-z]):[\\/]*(.*)$", value)
    if not match:
        return value
    drive = match.group(1).lower()
    rest = match.group(2).replace("\\", "/").strip("/")
    return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"


def path_from_user_value(value: str) -> Path:
    return Path(normalize_local_path(value)).expanduser().resolve()


def load_runtime_paths(settings: dict[str, Any] | None = None) -> RuntimePaths:
    settings = settings or {}
    appdata_override = os.environ.get("TIMELINE_FOR_IMAGE_APPDATA_ROOT")
    settings_appdata = settings.get("appdata_root")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if appdata_override:
        appdata_root = path_from_user_value(appdata_override)
    elif isinstance(settings_appdata, str) and settings_appdata:
        appdata_root = path_from_user_value(settings_appdata)
    elif local_app_data:
        appdata_root = (Path(local_app_data) / "TimelineForImage").resolve()
    else:
        appdata_root = (Path.home() / ".timeline-for-image").resolve()

    outputs_override = os.environ.get("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT")
    settings_outputs = settings.get("outputs_root")
    if outputs_override:
        outputs_root = path_from_user_value(outputs_override)
    elif isinstance(settings_outputs, str) and settings_outputs:
        outputs_root = path_from_user_value(settings_outputs)
    else:
        outputs_root = appdata_root / "outputs"
    return RuntimePaths(
        appdata_root=appdata_root,
        outputs_root=outputs_root,
        state_root=appdata_root / "state",
    )
