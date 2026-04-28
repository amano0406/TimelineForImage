from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .contracts import CaptionRecord, ImageItem

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_LOCAL_MODEL = "Salesforce/blip-image-captioning-base"
_HF_PIPELINES: dict[str, Any] = {}


def caption_images(items: list[ImageItem], mode: str, model: str | None) -> list[CaptionRecord]:
    if mode == "off":
        return []
    if mode == "mock":
        return [_mock_caption(item) for item in items]
    if mode == "local":
        resolved_model = resolve_caption_model(mode, model)
        return [_local_hf_caption(item, resolved_model) for item in items]
    if mode == "openai":
        resolved_model = resolve_caption_model(mode, model)
        return [_openai_caption(item, resolved_model) for item in items]
    raise ValueError(f"Unsupported caption mode: {mode}")


def resolve_caption_model(mode: str, model: str | None) -> str | None:
    if mode == "local":
        return model or os.environ.get("TIMELINE_FOR_IMAGE_LOCAL_MODEL") or DEFAULT_LOCAL_MODEL
    if mode == "openai":
        return model or os.environ.get("TIMELINE_FOR_IMAGE_CAPTION_MODEL") or DEFAULT_OPENAI_MODEL
    return model


def check_local_caption_backend(model: str | None = None) -> dict[str, object]:
    resolved_model = model or os.environ.get("TIMELINE_FOR_IMAGE_LOCAL_MODEL") or DEFAULT_LOCAL_MODEL
    payload: dict[str, object] = {
        "model": resolved_model,
        "backend": "huggingface-local",
        "dependencies_available": False,
        "model_loadable": False,
        "warning": None,
    }
    try:
        _load_hf_pipeline(resolved_model)
        payload["dependencies_available"] = True
        payload["model_loadable"] = True
    except Exception as exc:
        payload["warning"] = f"Hugging Face local backend is not ready: {exc}"
    return payload


def _mock_caption(item: ImageItem) -> CaptionRecord:
    dimensions = f"{item.width}x{item.height}" if item.width and item.height else "unknown size"
    timestamp = item.captured_at or item.modified_at
    text = (
        f"Mock caption for {item.relative_path}: {item.format_name} image, "
        f"{dimensions}, timeline timestamp {timestamp}. Image content was not inspected."
    )
    return CaptionRecord(
        source_path=item.source_path,
        mode="mock",
        model=None,
        text=text,
        warnings=["mock caption; image content was not inspected"],
    )


def _openai_caption(item: ImageItem, model: str) -> CaptionRecord:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return CaptionRecord(
            source_path=item.source_path,
            mode="openai",
            model=model,
            text="",
            warnings=["OPENAI_API_KEY is not set; caption skipped"],
        )

    path = Path(item.source_path)
    try:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        mime_type = _mime_type(item.format_name)
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Describe this image in Japanese for a personal timeline. "
                                "Keep it concise. Mention visible scene, objects, activities, "
                                "text if readable, and uncertainty. Do not identify private people by name."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
            "max_tokens": 300,
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        text = response_payload["choices"][0]["message"]["content"].strip()
        return CaptionRecord(source_path=item.source_path, mode="openai", model=model, text=text)
    except (OSError, KeyError, IndexError, json.JSONDecodeError, urllib.error.URLError) as exc:
        return CaptionRecord(
            source_path=item.source_path,
            mode="openai",
            model=model,
            text="",
            warnings=[f"caption failed: {exc}"],
        )


def _local_hf_caption(item: ImageItem, model: str) -> CaptionRecord:
    path = Path(item.source_path)
    try:
        pipe = _load_hf_pipeline(model)
        result = pipe(str(path))
        text = _extract_generated_text(result)
        warnings = [] if text else ["local model returned an empty caption"]
        return CaptionRecord(
            source_path=item.source_path,
            mode="local",
            model=model,
            text=text,
            warnings=warnings,
        )
    except Exception as exc:
        return CaptionRecord(
            source_path=item.source_path,
            mode="local",
            model=model,
            text="",
            warnings=[f"Hugging Face local caption failed: {exc}"],
        )


def _load_hf_pipeline(model: str) -> Any:
    if model not in _HF_PIPELINES:
        from transformers import pipeline

        _HF_PIPELINES[model] = pipeline("image-to-text", model=model)
    return _HF_PIPELINES[model]


def _extract_generated_text(result: Any) -> str:
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            return str(first.get("generated_text", "")).strip()
        return str(first).strip()
    if isinstance(result, dict):
        return str(result.get("generated_text", "")).strip()
    return str(result or "").strip()


def _mime_type(format_name: str) -> str:
    normalized = format_name.upper()
    if normalized == "JPEG":
        return "image/jpeg"
    if normalized == "PNG":
        return "image/png"
    if normalized == "GIF":
        return "image/gif"
    if normalized == "WEBP":
        return "image/webp"
    if normalized == "BMP":
        return "image/bmp"
    return "application/octet-stream"
