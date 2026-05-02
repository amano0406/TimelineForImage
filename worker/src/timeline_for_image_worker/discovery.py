from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageOps

from .contracts import ImageSource
from .fs_utils import safe_relative_path, utc_from_timestamp

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def discover_images(input_roots: list[Path]) -> list[ImageSource]:
    roots = [root.resolve() for root in input_roots]
    paths: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() in SUPPORTED_EXTENSIONS:
            paths.append(root)
        elif root.is_dir():
            paths.extend(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS)
    return [read_image_source(path, roots) for path in sorted(set(paths))]


def read_image_source(path: Path, roots: list[Path]) -> ImageSource:
    data = path.read_bytes()
    stat = path.stat()
    warnings: list[str] = []
    width: int | None = None
    height: int | None = None
    format_name = path.suffix.lower().lstrip(".").upper() or "UNKNOWN"
    captured_at = None
    camera_make = None
    camera_model = None
    try:
        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw)
            width, height = image.size
            format_name = str(raw.format or format_name)
            exif = raw.getexif()
            captured_at = _exif_datetime(exif.get(36867) or exif.get(306))
            camera_make = _clean_exif_text(exif.get(271))
            camera_model = _clean_exif_text(exif.get(272))
    except Exception as exc:
        warnings.append(f"image metadata read failed: {exc}")
    if captured_at is None:
        warnings.append("capture timestamp unavailable; using file modified timestamp")
    sha256 = hashlib.sha256(data).hexdigest()
    relative_path = safe_relative_path(path, roots)
    return ImageSource(
        item_id=_item_id(sha256, relative_path),
        source_path=str(path.resolve()),
        relative_path=relative_path,
        display_name=path.name,
        sha256=sha256,
        size_bytes=len(data),
        modified_at=utc_from_timestamp(stat.st_mtime),
        format_name=format_name,
        width=width,
        height=height,
        captured_at=captured_at,
        camera_make=camera_make,
        camera_model=camera_model,
        warnings=warnings,
    )


def _item_id(sha256: str, relative_path: str) -> str:
    digest = hashlib.sha256(f"{sha256}|{relative_path}".encode("utf-8")).hexdigest()[:16]
    return f"image-{digest}"


def _exif_datetime(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # EXIF timestamps usually have no timezone. Keep the product contract explicit by normalizing as UTC.
    if len(text) >= 19 and text[4] == ":" and text[7] == ":":
        return f"{text[:4]}-{text[5:7]}-{text[8:10]}T{text[11:19]}+00:00"
    return None


def _clean_exif_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
