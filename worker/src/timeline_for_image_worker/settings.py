from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .fs_utils import read_json, write_json


@dataclass(frozen=True)
class RuntimeSettings:
    instance_name: str
    api_port: int


@dataclass(frozen=True)
class Settings:
    schema_version: int
    input_roots: list[str]
    output_root: str
    compute_mode: str
    runtime: RuntimeSettings
    huggingface_token: str | None = None


SETTINGS_SCHEMA_VERSION = 1
SETTINGS_KEYS = ("schemaVersion", "runtime", "inputRoots", "outputRoot", "huggingfaceToken", "computeMode")
REQUIRED_SETTINGS_KEYS = ("schemaVersion", "runtime", "inputRoots", "outputRoot", "computeMode")
RUNTIME_KEYS = ("instanceName", "apiPort")
REQUIRED_RUNTIME_KEYS = ("instanceName", "apiPort")
COMPUTE_MODES = ("auto", "cpu", "gpu")
DEFAULT_COMPUTE_MODE = "gpu"
DEFAULT_API_PORT = 19400
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
    missing = [key for key in REQUIRED_SETTINGS_KEYS if key not in payload]
    if missing:
        raise ValueError(f"settings.json is missing required keys: {', '.join(missing)}")
    schema_version = int(payload["schemaVersion"])
    if schema_version != SETTINGS_SCHEMA_VERSION:
        raise ValueError(f"Unsupported schemaVersion: {schema_version}")
    if not isinstance(payload["inputRoots"], list):
        raise ValueError("inputRoots must be an array.")
    input_roots = normalize_path_list(payload["inputRoots"], "inputRoots")
    output_root = normalize_path_string(payload["outputRoot"], "outputRoot")
    compute_mode = normalize_compute_mode(payload["computeMode"])
    huggingface_token = normalize_optional_secret(payload.get("huggingfaceToken"), "huggingfaceToken")
    runtime = normalize_runtime(payload["runtime"])
    return Settings(
        schema_version=schema_version,
        input_roots=input_roots,
        output_root=output_root,
        compute_mode=compute_mode,
        runtime=runtime,
        huggingface_token=huggingface_token,
    )


def save_settings(settings: Settings) -> None:
    write_json(settings_path(), settings_to_payload(settings))


def settings_to_payload(settings: Settings, *, include_secrets: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": settings.schema_version,
        "runtime": {
            "instanceName": settings.runtime.instance_name,
            "apiPort": settings.runtime.api_port,
        },
        "inputRoots": settings.input_roots,
        "outputRoot": settings.output_root,
    }
    if settings.huggingface_token is not None and include_secrets:
        payload["huggingfaceToken"] = settings.huggingface_token
    payload["computeMode"] = settings.compute_mode
    return payload


def settings_to_cli_payload(settings: Settings, *, include_secrets: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": settings.schema_version,
        "input_roots": settings.input_roots,
        "output_root": settings.output_root,
        "compute_mode": settings.compute_mode,
        "runtime": {
            "instance_name": settings.runtime.instance_name,
            "api_port": settings.runtime.api_port,
        },
    }
    if settings.huggingface_token is not None and include_secrets:
        payload["huggingface_token"] = settings.huggingface_token
    return payload


def default_settings_payload() -> dict[str, Any]:
    return {
        "schemaVersion": SETTINGS_SCHEMA_VERSION,
        "runtime": {
            "instanceName": "",
            "apiPort": DEFAULT_API_PORT,
        },
        "inputRoots": ["C:\\TimelineData\\input-image\\"],
        "outputRoot": "C:\\TimelineData\\image",
        "computeMode": DEFAULT_COMPUTE_MODE,
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


def normalize_compute_mode(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("computeMode must be a string.")
    normalized = value.strip().lower()
    if normalized not in COMPUTE_MODES:
        raise ValueError(f"computeMode must be one of: {', '.join(COMPUTE_MODES)}.")
    return normalized


def normalize_optional_secret(value: Any, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string.")
    normalized = value.strip()
    return normalized or None


def normalize_runtime(value: Any) -> RuntimeSettings:
    if not isinstance(value, dict):
        raise ValueError("runtime must be an object.")
    unknown = sorted(set(value) - set(RUNTIME_KEYS))
    if unknown:
        raise ValueError(f"runtime has unsupported keys: {', '.join(unknown)}")
    missing = [key for key in REQUIRED_RUNTIME_KEYS if key not in value]
    if missing:
        raise ValueError(f"runtime is missing required keys: {', '.join(missing)}")
    instance_name = str(value.get("instanceName") or "").strip()
    try:
        api_port = int(value["apiPort"])
    except (TypeError, ValueError) as exc:
        raise ValueError("runtime.apiPort must be an integer.") from exc
    if api_port < 1 or api_port > 65535:
        raise ValueError("runtime.apiPort must be a TCP port from 1 to 65535.")
    return RuntimeSettings(instance_name=instance_name, api_port=api_port)


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
