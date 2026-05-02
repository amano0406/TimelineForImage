from __future__ import annotations


def list_models() -> list[dict[str, object]]:
    return [
        {
            "id": "pillow",
            "role": "metadata_and_color_layout",
            "local": True,
            "external_api": False,
            "notes": "Reads image dimensions, EXIF metadata, normalized JPEG artifacts, palette, and grid colors.",
        },
        {
            "id": "tesseract:jpn+eng",
            "role": "ocr",
            "local": True,
            "external_api": False,
            "notes": "Local OCR inside the worker container. OCR text is not privacy-redacted.",
        },
    ]
