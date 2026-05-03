from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

from jsonschema import Draft202012Validator
import timeline_for_image_worker.cli as cli
from timeline_for_image_worker.cli import main
from timeline_for_image_worker.discovery import discover_images

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_RECORD_SCHEMA = json.loads((REPO_ROOT / "schemas" / "image_record.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(IMAGE_RECORD_SCHEMA)
IMAGE_RECORD_VALIDATOR = Draft202012Validator(IMAGE_RECORD_SCHEMA)


def test_discover_png_dimensions(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(minimal_png(3, 2))

    items = discover_images([tmp_path])

    assert len(items) == 1
    assert items[0].width == 3
    assert items[0].height == 2
    assert items[0].format_name == "PNG"


def test_host_cli_is_blocked_outside_docker(monkeypatch, capsys) -> None:
    monkeypatch.delenv("TIMELINE_FOR_IMAGE_IN_DOCKER", raising=False)
    monkeypatch.setattr(cli, "is_in_docker", lambda: False)
    assert main(["doctor"]) == 1
    assert "Host CLI execution is disabled" in capsys.readouterr().err


def test_settings_reject_removed_keys(tmp_path: Path, monkeypatch, capsys) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "inputRoots": [str(tmp_path)],
                "outputRoot": str(tmp_path / "output"),
                "appdataRoot": str(tmp_path / "appdata"),
                "ocrMode": "mock",
                "removedSetting": "value",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["doctor"]) == 1
    assert "unsupported keys: removedSetting" in capsys.readouterr().err


def test_refresh_creates_master_item_artifacts(tmp_path: Path, monkeypatch) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    appdata_root = tmp_path / "appdata"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    (input_root / "sample.png").write_bytes(minimal_png(8, 6))
    write_test_settings(settings_path, input_root, output_root, appdata_root, ocr_mode="mock")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
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
    IMAGE_RECORD_VALIDATOR.validate(record)
    assert record["text"]["has_text"] is True
    assert record["layout"]["color_palette"]
    assert record["layout"]["grid"]
    latest_zip = output_root / "latest" / "TimelineForImage-export.zip"
    assert latest_zip.exists()
    with zipfile.ZipFile(latest_zip) as archive:
        assert f"items/{item_dir.name}/image_record.json" in archive.namelist()


def test_items_list_paging_and_remove_generated_artifacts_only(tmp_path: Path, monkeypatch, capsys) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    appdata_root = tmp_path / "appdata"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    source = input_root / "sample.png"
    source.write_bytes(minimal_png(8, 6))
    write_test_settings(settings_path, input_root, output_root, appdata_root, ocr_mode="mock")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["--json", "items", "refresh"]) == 0
    capsys.readouterr()
    assert main(["--json", "items", "list", "--page", "1", "--page-size", "1"]) == 0
    list_payload = json.loads(capsys.readouterr().out)
    item_id = list_payload["items"][0]["item_id"]
    item_dir = Path(list_payload["items"][0]["output_dir"])
    assert item_dir.exists()

    assert main(["--json", "items", "remove", "--item-id", item_id, "--dry-run"]) == 0
    dry_run_payload = json.loads(capsys.readouterr().out)
    assert dry_run_payload["dry_run"] is True
    assert dry_run_payload["removed_count"] == 1
    assert item_dir.exists()
    assert source.exists()

    assert main(["--json", "items", "remove", "--item-id", item_id]) == 0
    remove_payload = json.loads(capsys.readouterr().out)
    assert remove_payload["dry_run"] is False
    assert remove_payload["removed_count"] == 1
    assert remove_payload["source_images_removed"] is False
    assert not item_dir.exists()
    assert source.exists()

    assert main(["--json", "items", "list"]) == 0
    empty_payload = json.loads(capsys.readouterr().out)
    assert empty_payload["count"] == 0


def test_doctor_reports_validation_and_run_show_has_artifacts(tmp_path: Path, monkeypatch, capsys) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    appdata_root = tmp_path / "appdata"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    (input_root / "sample.png").write_bytes(minimal_png(8, 6))
    write_test_settings(settings_path, input_root, output_root, appdata_root, ocr_mode="mock")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["--json", "doctor"]) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["ok"] is True
    assert doctor_payload["input_roots"][0]["supported_image_count"] == 1

    assert main(["--json", "items", "refresh"]) == 0
    refresh_payload = json.loads(capsys.readouterr().out)
    run_id = refresh_payload["run_id"]

    assert main(["--json", "runs", "show", "--run-id", run_id]) == 0
    show_payload = json.loads(capsys.readouterr().out)
    assert show_payload["result"]["processed_count"] == 1
    assert show_payload["items"][0]["artifacts"]["output_dir_exists"] is True
    assert show_payload["items"][0]["artifacts"]["image_record"].endswith("image_record.json")


def write_test_settings(
    settings_path: Path,
    input_root: Path,
    output_root: Path,
    appdata_root: Path,
    *,
    ocr_mode: str,
) -> None:
    settings_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "inputRoots": [str(input_root)],
                "outputRoot": str(output_root),
                "appdataRoot": str(appdata_root),
                "ocrMode": ocr_mode,
            }
        ),
        encoding="utf-8",
    )


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
