from __future__ import annotations

import os
from pathlib import Path

from .contracts import ImageItem, OcrRecord

DEFAULT_OCR_MODEL = "tesseract:eng+jpn"


def run_ocr(items: list[ImageItem], mode: str, model: str | None) -> list[OcrRecord]:
    if mode == "off":
        return []
    if mode == "mock":
        return [_mock_ocr(item) for item in items]
    if mode in {"auto", "always"}:
        resolved_model = resolve_ocr_model(mode, model)
        return [_local_ocr(item, mode, resolved_model) for item in items]
    raise ValueError(f"Unsupported OCR mode: {mode}")


def resolve_ocr_model(mode: str, model: str | None) -> str | None:
    if mode in {"auto", "always"}:
        return model or os.environ.get("TIMELINE_FOR_IMAGE_OCR_MODEL") or DEFAULT_OCR_MODEL
    return model


def _mock_ocr(item: ImageItem) -> OcrRecord:
    return OcrRecord(
        source_path=item.source_path,
        mode="mock",
        model=None,
        should_run=True,
        check_text="MOCK YES",
        text=f"Mock OCR for {item.relative_path}",
        warnings=["mock OCR; image text was not inspected"],
    )


def _local_ocr(item: ImageItem, mode: str, model: str) -> OcrRecord:
    text, warnings = _read_text_with_local_ocr(item, model)
    should_run = mode == "always" or bool(text)
    check_text = "FORCED" if mode == "always" else ("YES" if text else "NO")
    return OcrRecord(
        source_path=item.source_path,
        mode=mode,
        model=model,
        should_run=should_run,
        check_text=check_text,
        text=text,
        warnings=warnings,
    )


def _read_text_with_local_ocr(item: ImageItem, model: str) -> tuple[str, list[str]]:
    path = Path(item.source_path)
    try:
        from PIL import Image
        import pytesseract

        lang = _resolve_tesseract_lang(model)
        with Image.open(path) as image:
            text = pytesseract.image_to_string(image, lang=lang)
        return text.strip(), []
    except Exception as exc:
        return "", [f"local OCR failed: {exc}"]


def _resolve_tesseract_lang(model: str) -> str:
    if model.startswith("tesseract:"):
        return model.split(":", 1)[1] or "eng"
    return os.environ.get("TIMELINE_FOR_IMAGE_OCR_LANG") or model or "eng"
