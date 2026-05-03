from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
import timeline_for_image_worker.cli as cli
from timeline_for_image_worker.cli import main
from timeline_for_image_worker.discovery import discover_images
from timeline_for_image_worker.locks import LockTimeoutError, exclusive_lock
from timeline_for_image_worker.settings import Settings, default_settings_payload, load_settings, settings_to_payload

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_RECORD_SCHEMA = json.loads((REPO_ROOT / "schemas" / "image_record.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(IMAGE_RECORD_SCHEMA)
IMAGE_RECORD_VALIDATOR = Draft202012Validator(IMAGE_RECORD_SCHEMA)
SETTINGS_SCHEMA = json.loads((REPO_ROOT / "schemas" / "settings.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SETTINGS_SCHEMA)
SETTINGS_VALIDATOR = Draft202012Validator(SETTINGS_SCHEMA)


def test_discover_png_dimensions(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(minimal_png(3, 2))

    items = discover_images([tmp_path])

    assert len(items) == 1
    assert items[0].width == 3
    assert items[0].height == 2
    assert items[0].format_name == "PNG"


def test_files_list_json_reports_input_images(tmp_path: Path, monkeypatch, capsys) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    state_root = tmp_path / "state"
    settings_path = tmp_path / "settings.json"
    nested = input_root / "nested"
    nested.mkdir(parents=True)
    (input_root / "sample-a.png").write_bytes(minimal_png(8, 6))
    (nested / "sample-b.png").write_bytes(minimal_png(3, 2))
    write_test_settings(settings_path, input_root, output_root)
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["--json", "files", "list", "--page", "1", "--page-size", "10"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 2
    assert payload["page_count"] == 1
    assert len(payload["files"]) == 2
    by_path = {row["relative_path"]: row for row in payload["files"]}
    assert set(by_path) == {"sample-a.png", "nested/sample-b.png"}
    first = by_path["sample-a.png"]
    assert first["item_id"].startswith("image-")
    assert first["format_name"] == "PNG"
    assert first["width"] == 8
    assert first["height"] == 6
    assert first["sha256"]


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
                "removedSetting": "value",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["doctor"]) == 1
    assert "unsupported keys: removedSetting" in capsys.readouterr().err


def test_settings_contract_is_public_three_key_schema() -> None:
    payload = default_settings_payload()
    assert set(payload) == {"schemaVersion", "inputRoots", "outputRoot"}
    SETTINGS_VALIDATOR.validate(payload)
    SETTINGS_VALIDATOR.validate(
        settings_to_payload(Settings(schema_version=1, input_roots=["C:\\Images"], output_root="C:\\TimelineData\\image"))
    )

    removed_keys = [
        "ocr",
        "ocr" + "Mode",
        "state" + "Root",
        "state" + "Directory",
        "cache" + "Root",
        "test" + "Mode",
    ]
    for removed_key in removed_keys:
        invalid_payload = {**payload, removed_key: "legacy"}
        errors = list(SETTINGS_VALIDATOR.iter_errors(invalid_payload))
        assert errors, f"{removed_key} must not be accepted by settings.schema.json"


def test_settings_reject_invalid_path_values(tmp_path: Path, monkeypatch) -> None:
    settings_path = tmp_path / "settings.json"
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    invalid_payloads = [
        (
            {
                "schemaVersion": 1,
                "inputRoots": [],
                "outputRoot": str(tmp_path / "output"),
            },
            "inputRoots must contain at least one path.",
        ),
        (
            {
                "schemaVersion": 1,
                "inputRoots": [""],
                "outputRoot": str(tmp_path / "output"),
            },
            "inputRoots[0] must not be empty.",
        ),
        (
            {
                "schemaVersion": 1,
                "inputRoots": [str(tmp_path)],
                "outputRoot": "   ",
            },
            "outputRoot must not be empty.",
        ),
        (
            {
                "schemaVersion": 1,
                "inputRoots": [str(tmp_path)],
                "outputRoot": None,
            },
            "outputRoot must be a string.",
        ),
    ]

    for payload, message in invalid_payloads:
        settings_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError) as exc_info:
            load_settings()
        assert message in str(exc_info.value)


def test_refresh_creates_master_item_artifacts(tmp_path: Path, monkeypatch) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    state_root = tmp_path / "state"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    (input_root / "sample.png").write_bytes(minimal_png(8, 6))
    write_test_settings(settings_path, input_root, output_root)
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT", str(state_root))
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
    assert record["layout"]["color_palette"]
    assert record["layout"]["grid"]
    latest_zip = output_root / "latest" / "TimelineForImage-export.zip"
    assert latest_zip.exists()
    with zipfile.ZipFile(latest_zip) as archive:
        assert f"items/{item_dir.name}/image_record.json" in archive.namelist()


def test_refresh_skips_no_changes_without_creating_run(tmp_path: Path, monkeypatch, capsys) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    state_root = tmp_path / "state"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    (input_root / "sample.png").write_bytes(minimal_png(8, 6))
    write_test_settings(settings_path, input_root, output_root)
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["--json", "items", "refresh"]) == 0
    capsys.readouterr()
    assert main(["--json", "items", "refresh"]) == 0
    no_change = json.loads(capsys.readouterr().out)
    assert no_change["state"] == "skipped_no_changes"
    assert no_change["run_id"] is None
    assert no_change["processed_count"] == 0
    assert no_change["skipped_count"] == 1

    assert main(["--json", "runs", "list"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert runs["count"] == 1


def test_serve_once_refreshes_and_exits(tmp_path: Path, monkeypatch, capsys) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    state_root = tmp_path / "state"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    (input_root / "sample.png").write_bytes(minimal_png(8, 6))
    write_test_settings(settings_path, input_root, output_root)
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["--json", "serve", "--once", "--interval-seconds", "1"]) == 0
    event = json.loads(capsys.readouterr().out)
    assert event["event"] == "refresh_completed"
    assert event["processed_count"] == 1
    assert len(list((output_root / "items").glob("*/image_record.json"))) == 1

    assert main(["--json", "serve", "--once", "--interval-seconds", "1"]) == 0
    second_event = json.loads(capsys.readouterr().out)
    assert second_event["event"] == "refresh_skipped_no_changes"
    assert second_event["run_id"] is None
    assert second_event["processed_count"] == 0
    assert second_event["skipped_count"] == 1


def test_operation_lock_times_out_when_already_held(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    with exclusive_lock(state_root, "catalog", timeout_seconds=0.1):
        with pytest.raises(LockTimeoutError):
            with exclusive_lock(state_root, "catalog", timeout_seconds=0.1, poll_interval_seconds=0.01):
                pass


def test_items_list_paging_and_remove_generated_artifacts_only(tmp_path: Path, monkeypatch, capsys) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    state_root = tmp_path / "state"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    source = input_root / "sample.png"
    source.write_bytes(minimal_png(8, 6))
    write_test_settings(settings_path, input_root, output_root)
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT", str(state_root))
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


def test_items_list_uses_current_output_root_and_download_to_destination(tmp_path: Path, monkeypatch, capsys) -> None:
    input_root = tmp_path / "input"
    first_output_root = tmp_path / "output-one"
    second_output_root = tmp_path / "output-two"
    state_root = tmp_path / "state"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    (input_root / "sample.png").write_bytes(minimal_png(8, 6))
    write_test_settings(settings_path, input_root, first_output_root)
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["--json", "items", "refresh"]) == 0
    capsys.readouterr()
    write_test_settings(settings_path, input_root, second_output_root)

    assert main(["--json", "items", "list"]) == 0
    stale_list_payload = json.loads(capsys.readouterr().out)
    assert stale_list_payload["count"] == 0

    assert main(["--json", "items", "refresh"]) == 0
    capsys.readouterr()
    target_dir = tmp_path / "handoff"
    assert main(["--json", "items", "download", "--all", "--to", str(target_dir)]) == 0
    download_payload = json.loads(capsys.readouterr().out)
    archive_path = Path(download_payload["archive_path"])
    assert archive_path == target_dir / "TimelineForImage-selected.zip"
    assert archive_path.exists()


def test_doctor_reports_validation_and_run_show_has_artifacts(tmp_path: Path, monkeypatch, capsys) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    state_root = tmp_path / "state"
    settings_path = tmp_path / "settings.json"
    input_root.mkdir()
    (input_root / "sample.png").write_bytes(minimal_png(8, 6))
    write_test_settings(settings_path, input_root, output_root)
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_IN_DOCKER", "1")
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_path))

    assert main(["--json", "doctor"]) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["ok"] is True
    assert doctor_payload["input_roots"][0]["supported_image_count"] == 1
    assert doctor_payload["state_root"]["path"] == str(state_root.resolve())

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
) -> None:
    settings_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "inputRoots": [str(input_root)],
                "outputRoot": str(output_root),
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
