from __future__ import annotations

import json
import os
import struct
import zipfile
from pathlib import Path

import timeline_for_image_worker.cli as cli
from timeline_for_image_worker.cli import main
from timeline_for_image_worker.discovery import discover_images


def test_discover_png_dimensions(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(minimal_png(3, 2))

    items = discover_images([tmp_path])

    assert len(items) == 1
    assert items[0].width == 3
    assert items[0].height == 2
    assert items[0].format_name == "PNG"


def test_host_cli_is_blocked_without_allow(monkeypatch, capsys) -> None:
    monkeypatch.delenv("TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI", raising=False)
    monkeypatch.delenv("TIMELINE_FOR_IMAGE_IN_DOCKER", raising=False)
    monkeypatch.setattr(cli, "is_in_docker", lambda: False)
    assert main(["doctor"]) == 1
    assert "Host CLI execution is disabled" in capsys.readouterr().err


def test_refresh_creates_master_item_artifacts(tmp_path: Path, monkeypatch) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    appdata_root = tmp_path / "appdata"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    (input_root / "sample.png").write_bytes(minimal_png(8, 6))
    settings_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "inputRoots": [str(input_root)],
                "outputRoot": str(output_root),
                "appdataRoot": str(appdata_root),
                "computeMode": "cpu",
                "ocrMode": "mock",
                "privacyFilter": "none",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["--json", "items", "refresh"]) == 0

    items_dir = output_root / "items"
    item_dirs = [path for path in items_dir.iterdir() if path.is_dir()]
    assert len(item_dirs) == 1
    item_dir = item_dirs[0]
    assert (item_dir / "convert_info.json").exists()
    assert (item_dir / "timeline.json").exists()
    assert (item_dir / "image_record.json").exists()
    assert (item_dir / "raw_outputs" / "ocr.json").exists()
    assert (item_dir / "artifacts" / "normalized_image.jpg").exists()
    assert (item_dir / "artifacts" / "debug_overlay.jpg").exists()
    record = json.loads((item_dir / "image_record.json").read_text(encoding="utf-8"))
    assert record["processing"]["privacy_filter"] == "none"
    assert record["text"]["has_text"] is True
    assert record["layout"]["color_palette"]
    assert record["layout"]["grid"]
    latest_zip = output_root / "latest" / "TimelineForImage-export.zip"
    assert latest_zip.exists()
    with zipfile.ZipFile(latest_zip) as archive:
        assert f"items/{item_dir.name}/image_record.json" in archive.namelist()


def minimal_png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        import zlib

        payload = kind + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    import zlib

    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
