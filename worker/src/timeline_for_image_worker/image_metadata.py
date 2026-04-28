from __future__ import annotations

import hashlib
import struct
from datetime import datetime, timezone
from pathlib import Path

from .contracts import ImageItem
from .fs_utils import safe_relative_path

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def read_image_item(path: Path, roots: list[Path], mock: bool = False) -> ImageItem:
    if mock:
        modified_at = _format_timestamp(path.stat().st_mtime) if path.exists() else "1970-01-01T00:00:00+00:00"
        return ImageItem(
            source_path=str(path.resolve()),
            relative_path=safe_relative_path(path, roots),
            sha256="0" * 64,
            size_bytes=path.stat().st_size if path.exists() else 0,
            format_name=_extension_format(path),
            width=1,
            height=1,
            captured_at=None,
            modified_at=modified_at,
            timeline_at=modified_at,
            camera_make=None,
            camera_model=None,
            lens_model=None,
            focal_length_mm=None,
            gps_latitude=None,
            gps_longitude=None,
            gps_altitude_m=None,
            warnings=["mock metadata"],
        )

    data = path.read_bytes()
    warnings: list[str] = []
    width, height, format_name = _read_dimensions(data, path)
    if width is None or height is None:
        warnings.append("image dimensions unavailable")

    exif_metadata = _read_exif_metadata(data) if format_name in {"JPEG", "TIFF"} else {}
    captured_at = _optional_string(exif_metadata.get("captured_at"))
    if captured_at is None:
        warnings.append("capture timestamp unavailable; using file modified timestamp")

    modified_at = _format_timestamp(path.stat().st_mtime)
    return ImageItem(
        source_path=str(path.resolve()),
        relative_path=safe_relative_path(path, roots),
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        format_name=format_name,
        width=width,
        height=height,
        captured_at=captured_at,
        modified_at=modified_at,
        timeline_at=captured_at or modified_at,
        camera_make=_optional_string(exif_metadata.get("camera_make")),
        camera_model=_optional_string(exif_metadata.get("camera_model")),
        lens_model=_optional_string(exif_metadata.get("lens_model")),
        focal_length_mm=_optional_float(exif_metadata.get("focal_length_mm")),
        gps_latitude=_optional_float(exif_metadata.get("gps_latitude")),
        gps_longitude=_optional_float(exif_metadata.get("gps_longitude")),
        gps_altitude_m=_optional_float(exif_metadata.get("gps_altitude_m")),
        warnings=warnings,
    )


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat()


def _extension_format(path: Path) -> str:
    return path.suffix.lower().lstrip(".").upper() or "UNKNOWN"


def _read_dimensions(data: bytes, path: Path) -> tuple[int | None, int | None, str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return width, height, "PNG"
    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return width, height, "GIF"
    if data.startswith(b"BM") and len(data) >= 26:
        width, height = struct.unpack("<ii", data[18:26])
        return abs(width), abs(height), "BMP"
    if data.startswith(b"\xff\xd8"):
        width, height = _read_jpeg_dimensions(data)
        return width, height, "JPEG"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        width, height = _read_webp_dimensions(data)
        return width, height, "WEBP"
    return None, None, _extension_format(path)


def _read_jpeg_dimensions(data: bytes) -> tuple[int | None, int | None]:
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            return None, None
        segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(data):
            return None, None
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_length >= 7:
                height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
                return width, height
            return None, None
        offset += segment_length
    return None, None


def _read_webp_dimensions(data: bytes) -> tuple[int | None, int | None]:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        start = data.find(b"\x9d\x01\x2a", 20)
        if start >= 0 and start + 7 <= len(data):
            width, height = struct.unpack("<HH", data[start + 3 : start + 7])
            return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    return None, None


def _read_exif_metadata(data: bytes) -> dict[str, object]:
    tiff = _extract_tiff_payload(data)
    if tiff is None or len(tiff) < 8:
        return {}
    endian = tiff[:2]
    if endian == b"II":
        order = "<"
    elif endian == b"MM":
        order = ">"
    else:
        return {}
    try:
        if struct.unpack(order + "H", tiff[2:4])[0] != 42:
            return {}
        ifd0_offset = struct.unpack(order + "I", tiff[4:8])[0]
        exif_ifd = _find_integer_value(tiff, ifd0_offset, 0x8769, order)
        gps_ifd = _find_integer_value(tiff, ifd0_offset, 0x8825, order)
        captured_at = None
        for ifd_offset in [exif_ifd, ifd0_offset]:
            if ifd_offset is None:
                continue
            raw = _find_ascii_value(tiff, ifd_offset, 0x9003, order) or _find_ascii_value(tiff, ifd_offset, 0x0132, order)
            parsed = _parse_exif_datetime(raw)
            if parsed is not None:
                captured_at = parsed
                break
        gps = _read_gps_metadata(tiff, gps_ifd, order) if gps_ifd is not None else {}
        return {
            "captured_at": captured_at,
            "camera_make": _find_ascii_value(tiff, ifd0_offset, 0x010F, order),
            "camera_model": _find_ascii_value(tiff, ifd0_offset, 0x0110, order),
            "lens_model": _find_ascii_value(tiff, exif_ifd, 0xA434, order) if exif_ifd is not None else None,
            "focal_length_mm": _find_rational_value(tiff, exif_ifd, 0x920A, order) if exif_ifd is not None else None,
            **gps,
        }
    except (IndexError, struct.error):
        return {}


def _extract_tiff_payload(data: bytes) -> bytes | None:
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return data
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if offset + 2 > len(data):
            return None
        segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
        segment = data[offset + 2 : offset + segment_length]
        if marker == 0xE1 and segment.startswith(b"Exif\x00\x00"):
            return segment[6:]
        offset += segment_length
    return None


def _find_ascii_value(tiff: bytes, ifd_offset: int, tag: int, order: str) -> str | None:
    entry = _find_entry(tiff, ifd_offset, tag, order)
    if entry is None:
        return None
    value_type, _, raw = entry
    if value_type != 2:
        return None
    return raw.rstrip(b"\x00").decode("ascii", errors="replace").strip() or None


def _find_integer_value(tiff: bytes, ifd_offset: int, tag: int, order: str) -> int | None:
    entry = _find_entry(tiff, ifd_offset, tag, order)
    if entry is None:
        return None
    value_type, value_count, raw = entry
    if value_count < 1:
        return None
    if value_type == 1 and len(raw) >= 1:
        return raw[0]
    if value_type == 3 and len(raw) >= 2:
        return struct.unpack(order + "H", raw[:2])[0]
    if value_type == 4 and len(raw) >= 4:
        return struct.unpack(order + "I", raw[:4])[0]
    return None


def _find_rational_value(tiff: bytes, ifd_offset: int, tag: int, order: str) -> float | None:
    values = _find_rational_values(tiff, ifd_offset, tag, order)
    return values[0] if values else None


def _find_rational_values(tiff: bytes, ifd_offset: int, tag: int, order: str) -> list[float]:
    entry = _find_entry(tiff, ifd_offset, tag, order)
    if entry is None:
        return []
    value_type, value_count, raw = entry
    if value_type not in {5, 10}:
        return []
    values: list[float] = []
    for index in range(value_count):
        chunk = raw[index * 8 : index * 8 + 8]
        if len(chunk) < 8:
            break
        if value_type == 5:
            numerator, denominator = struct.unpack(order + "II", chunk)
        else:
            numerator, denominator = struct.unpack(order + "ii", chunk)
        if denominator != 0:
            values.append(numerator / denominator)
    return values


def _find_entry(tiff: bytes, ifd_offset: int, tag: int, order: str) -> tuple[int, int, bytes] | None:
    if ifd_offset + 2 > len(tiff):
        return None
    count = struct.unpack(order + "H", tiff[ifd_offset : ifd_offset + 2])[0]
    cursor = ifd_offset + 2
    for _ in range(count):
        entry = tiff[cursor : cursor + 12]
        cursor += 12
        if len(entry) < 12:
            return None
        entry_tag, value_type, value_count, value_or_offset = struct.unpack(order + "HHII", entry)
        if entry_tag != tag:
            continue
        value_size = _tiff_value_size(value_type, value_count)
        if value_size is None:
            return None
        if value_size <= 4:
            raw = entry[8 : 8 + value_size]
        elif value_or_offset + value_size <= len(tiff):
            raw = tiff[value_or_offset : value_or_offset + value_size]
        else:
            return None
        return value_type, value_count, raw
    return None


def _tiff_value_size(value_type: int, value_count: int) -> int | None:
    type_sizes = {
        1: 1,
        2: 1,
        3: 2,
        4: 4,
        5: 8,
        7: 1,
        9: 4,
        10: 8,
    }
    unit_size = type_sizes.get(value_type)
    if unit_size is None:
        return None
    return unit_size * value_count


def _read_gps_metadata(tiff: bytes, ifd_offset: int, order: str) -> dict[str, float | None]:
    latitude_ref = _find_ascii_value(tiff, ifd_offset, 0x0001, order)
    latitude_values = _find_rational_values(tiff, ifd_offset, 0x0002, order)
    longitude_ref = _find_ascii_value(tiff, ifd_offset, 0x0003, order)
    longitude_values = _find_rational_values(tiff, ifd_offset, 0x0004, order)
    altitude_ref = _find_integer_value(tiff, ifd_offset, 0x0005, order)
    altitude = _find_rational_value(tiff, ifd_offset, 0x0006, order)
    return {
        "gps_latitude": _gps_coordinate(latitude_values, latitude_ref),
        "gps_longitude": _gps_coordinate(longitude_values, longitude_ref),
        "gps_altitude_m": -altitude if altitude is not None and altitude_ref == 1 else altitude,
    }


def _gps_coordinate(values: list[float], ref: str | None) -> float | None:
    if len(values) < 3:
        return None
    coordinate = values[0] + values[1] / 60 + values[2] / 3600
    if ref and ref.upper() in {"S", "W"}:
        coordinate *= -1
    return round(coordinate, 8)


def _parse_exif_datetime(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            return parsed.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
