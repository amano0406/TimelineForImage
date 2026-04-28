from __future__ import annotations

from pathlib import Path
from typing import Any

from .fs_utils import read_json

CAPTION_MODES = {"off", "mock", "local", "openai"}
OCR_MODES = {"off", "mock", "auto", "always"}


def load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path).expanduser().resolve()
    payload = read_json(config_path)
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {config_path}")
    _validate_config(payload, config_path)
    return payload


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def config_sources(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sources = config.get("sources", [])
    if raw_sources is None:
        return []
    if not isinstance(raw_sources, list):
        raise ValueError("Config sources must be a list.")

    sources = []
    for index, raw_source in enumerate(raw_sources):
        if isinstance(raw_source, str):
            sources.append({"path": raw_source, "recursive": True})
            continue
        if not isinstance(raw_source, dict):
            raise ValueError(f"Config sources[{index}] must be a string or object.")
        path = raw_source.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(f"Config sources[{index}].path must be a non-empty string.")
        recursive = raw_source.get("recursive", True)
        if not isinstance(recursive, bool):
            raise ValueError(f"Config sources[{index}].recursive must be a boolean.")
        sources.append({"path": path, "recursive": recursive})
    return sources


def nested_value(config: dict[str, Any], section: str, key: str, flat_key: str) -> Any:
    if flat_key in config:
        return config[flat_key]
    section_payload = config.get(section, {})
    if isinstance(section_payload, dict) and key in section_payload:
        return section_payload[key]
    return None


def _validate_config(config: dict[str, Any], config_path: Path) -> None:
    config_sources(config)
    _validate_optional_bool(config, "mock")
    _validate_optional_string(config, "appdata_root")
    _validate_optional_string(config, "outputs_root")
    _validate_optional_string(config, "annotations_file")
    _validate_optional_object(config, "caption", config_path)
    _validate_optional_object(config, "ocr", config_path)
    _validate_mode(nested_value(config, "caption", "mode", "caption_mode"), CAPTION_MODES, "caption.mode", config_path)
    _validate_optional_string_value(nested_value(config, "caption", "model", "caption_model"), "caption.model", config_path)
    _validate_mode(nested_value(config, "ocr", "mode", "ocr_mode"), OCR_MODES, "ocr.mode", config_path)
    _validate_optional_string_value(nested_value(config, "ocr", "model", "ocr_model"), "ocr.model", config_path)
    watch = config.get("watch", {})
    if watch is not None and not isinstance(watch, dict):
        raise ValueError(f"Config watch must be an object: {config_path}")
    if isinstance(watch, dict):
        _validate_optional_number(watch, "interval_seconds", minimum_exclusive=0)
        _validate_optional_number(watch, "min_quiet_seconds", minimum_inclusive=0)


def _validate_mode(value: Any, allowed: set[str], label: str, config_path: Path) -> None:
    if value is None:
        return
    if not isinstance(value, str) or value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"Config {label} must be one of {allowed_text}: {config_path}")


def _validate_optional_bool(config: dict[str, Any], key: str) -> None:
    if key in config and not isinstance(config[key], bool):
        raise ValueError(f"Config {key} must be a boolean.")


def _validate_optional_string(config: dict[str, Any], key: str) -> None:
    if key in config and config[key] is not None and not isinstance(config[key], str):
        raise ValueError(f"Config {key} must be a string.")


def _validate_optional_object(config: dict[str, Any], key: str, config_path: Path) -> None:
    if key in config and config[key] is not None and not isinstance(config[key], dict):
        raise ValueError(f"Config {key} must be an object: {config_path}")


def _validate_optional_string_value(value: Any, label: str, config_path: Path) -> None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Config {label} must be a string: {config_path}")


def _validate_optional_number(
    config: dict[str, Any],
    key: str,
    *,
    minimum_exclusive: float | None = None,
    minimum_inclusive: float | None = None,
) -> None:
    if key not in config:
        return
    value = config[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Config watch.{key} must be a number.")
    if minimum_exclusive is not None and value <= minimum_exclusive:
        raise ValueError(f"Config watch.{key} must be greater than {minimum_exclusive}.")
    if minimum_inclusive is not None and value < minimum_inclusive:
        raise ValueError(f"Config watch.{key} must be {minimum_inclusive} or greater.")
