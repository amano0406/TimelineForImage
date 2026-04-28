from __future__ import annotations

import json
import os
import struct
import zipfile
from pathlib import Path

import pytest
import timeline_for_image_worker.captioning as captioning
import timeline_for_image_worker.cli as cli
from timeline_for_image_worker.cli import main
from timeline_for_image_worker.discovery import discover_image_sources, discover_images
from timeline_for_image_worker.settings import normalize_local_path


@pytest.fixture(autouse=True)
def isolate_repo_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI", "1")


def test_discover_png_dimensions(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(_minimal_png(3, 2))

    items = discover_images([tmp_path], recursive=True)

    assert len(items) == 1
    assert items[0].format_name == "PNG"
    assert items[0].width == 3
    assert items[0].height == 2
    assert items[0].relative_path == "sample.png"


def test_host_cli_is_blocked_without_explicit_allow(monkeypatch, capsys) -> None:
    monkeypatch.delenv("TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI", raising=False)
    monkeypatch.delenv("TIMELINE_FOR_IMAGE_IN_DOCKER", raising=False)
    monkeypatch.setattr(cli, "_is_running_in_docker", lambda: False)

    assert main(["doctor", "--format", "json"]) == 1

    captured = capsys.readouterr()
    assert "Host CLI execution is disabled" in captured.err
    assert "docker compose --profile worker run --rm worker" in captured.err


def test_doctor_reports_settings_paths_sources_and_ocr(tmp_path: Path, monkeypatch, capsys) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    settings_file = tmp_path / "settings.json"
    input_dir.mkdir()
    output_dir.mkdir()
    appdata_dir.mkdir()
    settings_file.write_text(
        json.dumps(
            {
                "sources": [{"path": str(input_dir), "recursive": False}],
                "outputs_root": str(output_dir),
                "appdata_root": str(appdata_dir),
                "caption": {"mode": "off"},
                "ocr": {"mode": "off"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_file))
    monkeypatch.setattr(
        cli,
        "check_local_caption_backend",
        lambda model=None: {
            "model": "test-model",
            "backend": "huggingface-local",
            "dependencies_available": True,
            "model_loadable": True,
            "warning": None,
        },
    )

    assert main(["doctor", "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["settings"]["path"] == str(settings_file)
    assert payload["settings"]["exists"] is True
    assert payload["runtime_paths"]["outputs_root"] == str(output_dir.resolve())
    assert payload["sources"][0]["path"] == str(input_dir.resolve())
    assert payload["sources"][0]["recursive"] is False
    assert payload["sources"][0]["exists"] is True
    assert payload["ocr_backend"]["mode"] == "off"
    assert payload["ocr_backend"]["languages_available"] is True


def test_discover_jpeg_exif_camera_lens_and_gps(tmp_path: Path) -> None:
    image = tmp_path / "exif.jpg"
    image.write_bytes(_minimal_jpeg_with_exif())

    items = discover_images([tmp_path], recursive=True)

    assert len(items) == 1
    item = items[0]
    assert item.format_name == "JPEG"
    assert item.width == 3
    assert item.height == 2
    assert item.captured_at == "2026-04-28T12:34:56+00:00"
    assert item.timeline_at == "2026-04-28T12:34:56+00:00"
    assert item.camera_make == "Canon"
    assert item.camera_model == "EOS R5"
    assert item.lens_model == "RF 50mm F1.8"
    assert item.focal_length_mm == 50.0
    assert item.gps_latitude is not None
    assert item.gps_longitude is not None
    assert abs(item.gps_latitude - 35.68676111) < 0.000001
    assert abs(item.gps_longitude - 139.76577222) < 0.000001
    assert item.gps_altitude_m == 12.0


def test_run_creates_export_zip(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    result = main(["run", "--directory", str(input_dir), "--caption-mode", "mock", "--ocr-mode", "mock", "--format", "json"])

    assert result == 0
    jobs = _job_dirs(output_dir)
    assert len(jobs) == 1
    result_payload = json.loads((jobs[0] / "result.json").read_text(encoding="utf-8"))
    archive_path = Path(result_payload["archive_path"])
    assert archive_path.exists()
    assert (output_dir / "latest" / "timeline.md").exists()
    assert (output_dir / "latest" / "TimelineForImage-export.zip").exists()
    with zipfile.ZipFile(archive_path) as archive:
        assert sorted(archive.namelist()) == [
            "README.md",
            "annotations.json",
            "captions.json",
            "catalog.json",
            "fidelity_report.md",
            "manifest.json",
            "ocr.json",
            "timeline.md",
            "timeline_groups.json",
            "visual_observations.json",
        ]
    assert result_payload["reuse_summary"] == {"new": 1, "changed": 0, "unchanged": 0}
    assert result_payload["caption_count"] == 1
    assert result_payload["ocr_count"] == 1
    assert result_payload["ocr_ran_count"] == 1
    assert result_payload["visual_observation_count"] == 1
    assert result_payload["timeline_group_count"] == 1
    assert result_payload["annotation_count"] == 0
    captions = json.loads((jobs[0] / "captions.json").read_text(encoding="utf-8"))
    assert captions["captions"][0]["mode"] == "mock"
    ocr = json.loads((jobs[0] / "ocr.json").read_text(encoding="utf-8"))
    assert ocr["ocr"][0]["mode"] == "mock"
    assert ocr["ocr"][0]["should_run"] is True
    observations = json.loads((jobs[0] / "visual_observations.json").read_text(encoding="utf-8"))
    assert observations["visual_observations"][0]["has_text"] is True
    groups = json.loads((jobs[0] / "timeline_groups.json").read_text(encoding="utf-8"))
    assert groups["timeline_groups"][0]["group_type"] == "day"


def test_settings_init_creates_settings_json(tmp_path: Path, monkeypatch) -> None:
    settings_file = tmp_path / "settings.json"
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_file))

    assert main(["settings", "init", "--format", "json"]) == 0
    assert settings_file.exists()
    payload = json.loads(settings_file.read_text(encoding="utf-8"))
    assert payload["sources"][0]["path"] == "C:\\Users\\amano\\Pictures\\"
    assert payload["outputs_root"] == "C:\\Users\\amano\\image\\"

    assert main(["settings", "init", "--format", "json"]) == 0
    assert json.loads(settings_file.read_text(encoding="utf-8")) == payload


def test_settings_file_drives_run_and_output_root(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    settings_file = tmp_path / "settings.json"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    settings_file.write_text(
        json.dumps(
            {
                "sources": [{"path": str(input_dir), "recursive": True}],
                "outputs_root": str(output_dir),
                "appdata_root": str(appdata_dir),
                "caption": {"mode": "mock"},
                "ocr": {"mode": "mock"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_file))
    monkeypatch.delenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", raising=False)
    monkeypatch.delenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", raising=False)

    assert main(["run", "--format", "json"]) == 0

    job = _job_dirs(output_dir)[0]
    request = json.loads((job / "request.json").read_text(encoding="utf-8"))
    assert request["source_paths"] == [str(input_dir.resolve())]
    assert request["caption_mode"] == "mock"
    assert request["ocr_mode"] == "mock"
    assert (appdata_dir / "state" / "master_catalog.json").exists()


def test_settings_sources_keep_per_source_recursive(tmp_path: Path, monkeypatch) -> None:
    recursive_dir = tmp_path / "recursive"
    shallow_dir = tmp_path / "shallow"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    settings_file = tmp_path / "settings.json"
    (recursive_dir / "nested").mkdir(parents=True)
    (shallow_dir / "nested").mkdir(parents=True)
    (recursive_dir / "nested" / "included.png").write_bytes(_minimal_png(1, 1))
    (shallow_dir / "top.png").write_bytes(_minimal_png(1, 1))
    (shallow_dir / "nested" / "excluded.png").write_bytes(_minimal_png(1, 1))
    settings_file.write_text(
        json.dumps(
            {
                "sources": [
                    {"path": str(recursive_dir), "recursive": True},
                    {"path": str(shallow_dir), "recursive": False},
                ],
                "outputs_root": str(output_dir),
                "appdata_root": str(appdata_dir),
                "caption": {"mode": "off"},
                "ocr": {"mode": "off"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_SETTINGS_PATH", str(settings_file))
    monkeypatch.delenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", raising=False)
    monkeypatch.delenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", raising=False)

    assert main(["run", "--format", "json"]) == 0

    job = _job_dirs(output_dir)[0]
    request = json.loads((job / "request.json").read_text(encoding="utf-8"))
    catalog = json.loads((job / "catalog.json").read_text(encoding="utf-8"))
    assert request["recursive"] is False
    assert request["source_options"] == [
        {"path": str(recursive_dir.resolve()), "recursive": True},
        {"path": str(shallow_dir.resolve()), "recursive": False},
    ]
    assert sorted(item["relative_path"] for item in catalog["items"]) == ["nested/included.png", "top.png"]


def test_discover_image_sources_respects_mixed_recursive(tmp_path: Path) -> None:
    recursive_dir = tmp_path / "recursive"
    shallow_dir = tmp_path / "shallow"
    (recursive_dir / "nested").mkdir(parents=True)
    (shallow_dir / "nested").mkdir(parents=True)
    (recursive_dir / "nested" / "included.png").write_bytes(_minimal_png(1, 1))
    (shallow_dir / "top.png").write_bytes(_minimal_png(1, 1))
    (shallow_dir / "nested" / "excluded.png").write_bytes(_minimal_png(1, 1))

    items = discover_image_sources([(recursive_dir, True), (shallow_dir, False)])

    assert sorted(item.relative_path for item in items) == ["nested/included.png", "top.png"]


def test_windows_paths_are_normalized_on_linux() -> None:
    if os.name == "nt":
        assert normalize_local_path("C:\\Users\\amano\\Pictures\\") == "C:\\Users\\amano\\Pictures\\"
    else:
        assert normalize_local_path("C:\\Users\\amano\\Pictures\\") == "/mnt/c/Users/amano/Pictures"


def test_config_file_drives_run(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    config_file = tmp_path / "timeline-for-image.config.json"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    config_file.write_text(
        json.dumps(
            {
                "sources": [{"path": str(input_dir), "recursive": True}],
                "caption": {"mode": "mock"},
                "ocr": {"mode": "mock"},
                "watch": {"interval_seconds": 0.1, "min_quiet_seconds": 0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert main(["run", "--config", str(config_file), "--format", "json"]) == 0

    job = _job_dirs(output_dir)[0]
    request = json.loads((job / "request.json").read_text(encoding="utf-8"))
    result = json.loads((job / "result.json").read_text(encoding="utf-8"))
    assert request["source_paths"] == [str(input_dir.resolve())]
    assert request["caption_mode"] == "mock"
    assert request["ocr_mode"] == "mock"
    assert result["caption_count"] == 1
    assert result["ocr_ran_count"] == 1


def test_cli_values_override_config_file(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    config_file = tmp_path / "timeline-for-image.config.json"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    config_file.write_text(
        json.dumps(
            {
                "sources": [{"path": str(input_dir), "recursive": True}],
                "caption": {"mode": "off"},
                "ocr": {"mode": "off"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert main(["run", "--config", str(config_file), "--caption-mode", "mock", "--ocr-mode", "mock"]) == 0

    job = _job_dirs(output_dir)[0]
    request = json.loads((job / "request.json").read_text(encoding="utf-8"))
    assert request["caption_mode"] == "mock"
    assert request["ocr_mode"] == "mock"


def test_sources_can_drive_run_and_reuse_summary(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert main(["sources", "add", str(input_dir)]) == 0
    assert main(["run", "--caption-mode", "mock", "--ocr-mode", "mock", "--format", "json"]) == 0
    assert main(["run", "--caption-mode", "mock", "--ocr-mode", "mock", "--format", "json"]) == 0

    jobs = _job_dirs(output_dir)
    second_result = json.loads((jobs[-1] / "result.json").read_text(encoding="utf-8"))
    assert second_result["reuse_summary"] == {"new": 0, "changed": 0, "unchanged": 1}


def test_second_run_reuses_derived_cache(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert main(["run", "--directory", str(input_dir), "--caption-mode", "mock", "--ocr-mode", "mock", "--format", "json"]) == 0
    first_job = _job_dirs(output_dir)[-1]
    first_result = json.loads((first_job / "result.json").read_text(encoding="utf-8"))
    assert first_result["derived_cache_hit_count"] == 0
    assert first_result["derived_cache_miss_count"] == 1
    assert first_result["generated_caption_count"] == 1
    assert first_result["generated_ocr_count"] == 1

    assert main(["run", "--directory", str(input_dir), "--caption-mode", "mock", "--ocr-mode", "mock", "--format", "json"]) == 0
    second_job = _job_dirs(output_dir)[-1]
    second_result = json.loads((second_job / "result.json").read_text(encoding="utf-8"))
    assert second_result["reuse_summary"] == {"new": 0, "changed": 0, "unchanged": 1}
    assert second_result["derived_cache_hit_count"] == 1
    assert second_result["derived_cache_miss_count"] == 0
    assert second_result["reused_caption_count"] == 1
    assert second_result["generated_caption_count"] == 0
    assert second_result["reused_ocr_count"] == 1
    assert second_result["generated_ocr_count"] == 0


def test_watch_once_runs_then_skips_when_unchanged(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    args = [
        "watch",
        "--directory",
        str(input_dir),
        "--caption-mode",
        "mock",
        "--ocr-mode",
        "mock",
        "--once",
        "--min-quiet-seconds",
        "0",
        "--format",
        "json",
    ]
    assert main(args) == 0
    jobs = _job_dirs(output_dir)
    assert len(jobs) == 1
    result = json.loads((jobs[0] / "result.json").read_text(encoding="utf-8"))
    assert result["run_reason"] == "watch:new-file"
    assert (output_dir / "latest" / "result.json").exists()

    assert main(args) == 0
    assert len(_job_dirs(output_dir)) == 1


def test_watch_uses_config_file(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    config_file = tmp_path / "timeline-for-image.config.json"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    config_file.write_text(
        json.dumps(
            {
                "sources": [{"path": str(input_dir), "recursive": True}],
                "caption": {"mode": "mock"},
                "ocr": {"mode": "mock"},
                "watch": {"interval_seconds": 0.1, "min_quiet_seconds": 0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    args = ["watch", "--config", str(config_file), "--once", "--format", "json"]
    assert main(args) == 0
    assert len(_job_dirs(output_dir)) == 1
    result = json.loads((_job_dirs(output_dir)[0] / "result.json").read_text(encoding="utf-8"))
    assert result["run_reason"] == "watch:new-file"

    assert main(args) == 0
    assert len(_job_dirs(output_dir)) == 1


def test_close_timestamps_create_sequence_group(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    first = input_dir / "first.png"
    second = input_dir / "second.png"
    first.write_bytes(_minimal_png(1, 1))
    second.write_bytes(_minimal_png(1, 1))
    os.utime(first, (1_800_000_000, 1_800_000_000))
    os.utime(second, (1_800_000_300, 1_800_000_300))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert main(["run", "--directory", str(input_dir), "--caption-mode", "off", "--ocr-mode", "off", "--format", "json"]) == 0

    job = _job_dirs(output_dir)[0]
    groups = json.loads((job / "timeline_groups.json").read_text(encoding="utf-8"))["timeline_groups"]
    assert [group["group_type"] for group in groups] == ["day", "sequence"]
    assert groups[1]["item_count"] == 2


def test_annotations_create_event_group(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    annotation_file = tmp_path / "annotations.json"
    input_dir.mkdir()
    first = input_dir / "first.png"
    second = input_dir / "second.png"
    first.write_bytes(_minimal_png(1, 1))
    second.write_bytes(_minimal_png(1, 1))
    os.utime(first, (1_800_000_000, 1_800_000_000))
    os.utime(second, (1_800_007_200, 1_800_007_200))
    annotation_file.write_text(
        json.dumps(
            {
                "annotations": [
                    {"relative_path": "first.png", "event": "Tokyo walk"},
                    {"relative_path": "second.png", "event": "Tokyo walk"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert (
        main(
            [
                "run",
                "--directory",
                str(input_dir),
                "--caption-mode",
                "off",
                "--ocr-mode",
                "off",
                "--annotations-file",
                str(annotation_file),
                "--format",
                "json",
            ]
        )
        == 0
    )

    job = _job_dirs(output_dir)[0]
    groups = json.loads((job / "timeline_groups.json").read_text(encoding="utf-8"))["timeline_groups"]
    event_group = next(group for group in groups if group["group_type"] == "event")
    assert event_group["group_id"] == "event:tokyo-walk"
    assert event_group["item_count"] == 2


def test_nearby_gps_coordinates_create_location_group(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "first.jpg").write_bytes(_minimal_jpeg_with_exif())
    (input_dir / "second.jpg").write_bytes(_minimal_jpeg_with_exif())
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert main(["run", "--directory", str(input_dir), "--caption-mode", "off", "--ocr-mode", "off", "--format", "json"]) == 0

    job = _job_dirs(output_dir)[0]
    groups = json.loads((job / "timeline_groups.json").read_text(encoding="utf-8"))["timeline_groups"]
    location_group = next(group for group in groups if group["group_type"] == "location")
    assert location_group["item_count"] == 2
    assert "250 meters" in location_group["reasoning"]


def test_mock_mode_uses_placeholder_metadata(tmp_path: Path) -> None:
    image = tmp_path / "mock.jpg"
    image.write_bytes(b"not really a jpeg")

    items = discover_images([tmp_path], recursive=True, mock=True)

    assert len(items) == 1
    assert items[0].sha256 == "0" * 64
    assert items[0].width == 1
    assert items[0].warnings == ["mock metadata"]


def test_caption_mode_off_creates_empty_caption_file(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert main(["run", "--directory", str(input_dir), "--caption-mode", "off", "--ocr-mode", "off"]) == 0

    job = _job_dirs(output_dir)[0]
    captions = json.loads((job / "captions.json").read_text(encoding="utf-8"))
    assert captions == {"captions": []}
    ocr = json.loads((job / "ocr.json").read_text(encoding="utf-8"))
    assert ocr == {"ocr": []}
    observations = json.loads((job / "visual_observations.json").read_text(encoding="utf-8"))
    assert observations["visual_observations"][0]["warnings"]


def test_local_caption_mode_records_warning_when_huggingface_backend_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))
    monkeypatch.setattr(captioning, "_load_hf_pipeline", lambda model: (_ for _ in ()).throw(RuntimeError("backend unavailable")))

    assert main(["run", "--directory", str(input_dir), "--caption-mode", "local", "--ocr-mode", "off"]) == 0

    job = _job_dirs(output_dir)[0]
    captions = json.loads((job / "captions.json").read_text(encoding="utf-8"))
    assert captions["captions"][0]["mode"] == "local"
    assert captions["captions"][0]["model"] == "Salesforce/blip-image-captioning-base"
    assert captions["captions"][0]["warnings"]


def test_ocr_mode_mock_records_should_run_and_text(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert main(["run", "--directory", str(input_dir), "--caption-mode", "off", "--ocr-mode", "mock"]) == 0

    job = _job_dirs(output_dir)[0]
    ocr = json.loads((job / "ocr.json").read_text(encoding="utf-8"))
    assert ocr["ocr"][0]["should_run"] is True
    assert "Mock OCR" in ocr["ocr"][0]["text"]


def test_annotations_file_is_copied_into_outputs(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    appdata_dir = tmp_path / "appdata"
    output_dir = tmp_path / "outputs"
    annotation_file = tmp_path / "annotations.json"
    input_dir.mkdir()
    (input_dir / "sample.png").write_bytes(_minimal_png(1, 1))
    annotation_file.write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "relative_path": "sample.png",
                        "tags": ["receipt"],
                        "people": ["example person"],
                        "event": "test event",
                        "note": "manual note",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_APPDATA_ROOT", str(appdata_dir))
    monkeypatch.setenv("TIMELINE_FOR_IMAGE_OUTPUTS_ROOT", str(output_dir))

    assert (
        main(
            [
                "run",
                "--directory",
                str(input_dir),
                "--caption-mode",
                "mock",
                "--ocr-mode",
                "off",
                "--annotations-file",
                str(annotation_file),
            ]
        )
        == 0
    )

    job = _job_dirs(output_dir)[0]
    annotations = json.loads((job / "annotations.json").read_text(encoding="utf-8"))
    assert annotations["annotations"][0]["tags"] == ["receipt"]
    timeline = (job / "timeline.md").read_text(encoding="utf-8")
    assert "Human event: test event" in timeline


def _minimal_png(width: int, height: int) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00" + b"\x00\x00\x00\x00"
    iend = struct.pack(">I", 0) + b"IEND" + b"\x00\x00\x00\x00"
    return signature + ihdr + iend


def _job_dirs(output_dir: Path) -> list[Path]:
    return sorted(path for path in output_dir.iterdir() if path.name.startswith("job-"))


def _minimal_jpeg_with_exif() -> bytes:
    tiff = _test_tiff_payload()
    app1_payload = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(app1_payload) + 2) + app1_payload
    sof0_payload = b"\x08" + struct.pack(">HH", 2, 3) + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    sof0 = b"\xff\xc0" + struct.pack(">H", len(sof0_payload) + 2) + sof0_payload
    return b"\xff\xd8" + app1 + sof0 + b"\xff\xd9"


def _test_tiff_payload() -> bytes:
    ifd0_offset = 8
    ifd0_entries_without_pointers = [
        _ascii_entry(0x010F, "Canon"),
        _ascii_entry(0x0110, "EOS R5"),
        _ascii_entry(0x0132, "2026:04:28 12:34:56"),
    ]
    ifd0_size_with_pointers = _ifd_size([*ifd0_entries_without_pointers, _long_entry(0x8769, 0), _long_entry(0x8825, 0)])
    exif_offset = ifd0_offset + ifd0_size_with_pointers
    exif_entries = [
        _ascii_entry(0x9003, "2026:04:28 12:34:56"),
        _ascii_entry(0xA434, "RF 50mm F1.8"),
        _rational_entry(0x920A, [(50, 1)]),
    ]
    gps_offset = exif_offset + _ifd_size(exif_entries)
    ifd0_entries = [
        *ifd0_entries_without_pointers,
        _long_entry(0x8769, exif_offset),
        _long_entry(0x8825, gps_offset),
    ]
    gps_entries = [
        _ascii_entry(0x0001, "N"),
        _rational_entry(0x0002, [(35, 1), (41, 1), (1234, 100)]),
        _ascii_entry(0x0003, "E"),
        _rational_entry(0x0004, [(139, 1), (45, 1), (5678, 100)]),
        _byte_entry(0x0005, 0),
        _rational_entry(0x0006, [(12, 1)]),
    ]
    return (
        b"II*\x00"
        + struct.pack("<I", ifd0_offset)
        + _pack_ifd(ifd0_entries, ifd0_offset)
        + _pack_ifd(exif_entries, exif_offset)
        + _pack_ifd(gps_entries, gps_offset)
    )


def _ascii_entry(tag: int, value: str) -> tuple[int, int, int, bytes]:
    raw = value.encode("ascii") + b"\x00"
    return tag, 2, len(raw), raw


def _long_entry(tag: int, value: int) -> tuple[int, int, int, bytes]:
    return tag, 4, 1, struct.pack("<I", value)


def _byte_entry(tag: int, value: int) -> tuple[int, int, int, bytes]:
    return tag, 1, 1, bytes([value])


def _rational_entry(tag: int, values: list[tuple[int, int]]) -> tuple[int, int, int, bytes]:
    raw = b"".join(struct.pack("<II", numerator, denominator) for numerator, denominator in values)
    return tag, 5, len(values), raw


def _ifd_size(entries: list[tuple[int, int, int, bytes]]) -> int:
    extra_size = sum(len(raw) for _, _, _, raw in entries if len(raw) > 4)
    return 2 + len(entries) * 12 + 4 + extra_size


def _pack_ifd(entries: list[tuple[int, int, int, bytes]], ifd_offset: int) -> bytes:
    table_size = 2 + len(entries) * 12 + 4
    extra = bytearray()
    output = bytearray(struct.pack("<H", len(entries)))
    for tag, value_type, value_count, raw in entries:
        if len(raw) <= 4:
            value = raw.ljust(4, b"\x00")
        else:
            value = struct.pack("<I", ifd_offset + table_size + len(extra))
            extra.extend(raw)
        output.extend(struct.pack("<HHI", tag, value_type, value_count) + value)
    output.extend(struct.pack("<I", 0))
    output.extend(extra)
    return bytes(output)
