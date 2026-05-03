from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import Any

from .catalog import load_catalog, needs_processing, remove_catalog_item, save_catalog, update_catalog_item
from .contracts import ImageSource, RunStatus
from .discovery import discover_images
from .fs_utils import now_iso, read_json, write_json
from .image_record import build_image_record, save_debug_overlay, save_normalized_image
from .ocr import run_ocr
from .settings import Settings, internal_state_root, resolved_input_roots, resolved_output_root

OCR_MODE = "auto"


def refresh_items(settings: Settings, max_items: int | None = None, reprocess_duplicates: bool = False) -> dict[str, Any]:
    state_root = internal_state_root()
    output_root = resolved_output_root(settings)
    state_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = "run-" + now_iso().replace(":", "").replace("+", "Z")
    run_dir = state_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_status(run_dir, RunStatus(run_id=run_id, state="running", current_stage="discover", started_at=now_iso(), updated_at=now_iso()))

    sources = discover_images(resolved_input_roots(settings))
    catalog = load_catalog(state_root)
    candidates = [item for item in sources if needs_processing(catalog, item, reprocess_duplicates)]
    if max_items is not None:
        candidates = candidates[:max_items]
    results = []
    failed = 0
    for index, item in enumerate(candidates, start=1):
        write_status(
            run_dir,
            RunStatus(
                run_id=run_id,
                state="running",
                current_stage="process",
                items_total=len(candidates),
                items_done=index - 1,
                current_item=item.relative_path,
                progress_percent=round(((index - 1) / max(1, len(candidates))) * 100, 2),
                started_at=None,
                updated_at=now_iso(),
            ),
        )
        try:
            output_dir = process_image(item, output_root)
            update_catalog_item(catalog, item, output_dir)
            results.append({"item_id": item.item_id, "state": "processed", "output_dir": str(output_dir)})
        except Exception as exc:
            failed += 1
            results.append({"item_id": item.item_id, "state": "failed", "error": str(exc)})
    save_catalog(state_root, catalog)
    archive_path = create_download_zip(output_root, [Path(row["output_dir"]) for row in results if row.get("output_dir")])
    result = {
        "schema_version": 1,
        "run_id": run_id,
        "state": "completed" if failed == 0 else "completed_with_errors",
        "source_count": len(sources),
        "processed_count": len([row for row in results if row["state"] == "processed"]),
        "skipped_count": len(sources) - len(candidates),
        "failed_count": failed,
        "archive_path": str(archive_path) if archive_path else None,
        "items": results,
    }
    write_json(run_dir / "result.json", result)
    write_status(
        run_dir,
        RunStatus(
            run_id=run_id,
            state=result["state"],
            current_stage="completed",
            items_total=len(candidates),
            items_done=result["processed_count"],
            items_skipped=result["skipped_count"],
            items_failed=failed,
            progress_percent=100.0,
            updated_at=now_iso(),
            completed_at=now_iso(),
        ),
    )
    sync_latest(output_root, archive_path)
    return result


def process_image(item: ImageSource, output_root: Path) -> Path:
    item_dir = output_root / "items" / item.item_id
    raw_dir = item_dir / "raw_outputs"
    artifacts_dir = item_dir / "artifacts"
    raw_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    source = Path(item.source_path)
    ocr_payload = run_ocr(source, OCR_MODE)
    image_record = build_image_record(item, ocr_payload)
    timeline = build_timeline(item, image_record)
    convert_info = {
        "schema_version": 1,
        "product": "TimelineForImage",
        "item_id": item.item_id,
        "source": item.to_dict(),
        "pipeline": {
            "version": "timeline-for-image-local-v1",
            "source_image_modified": False,
        },
        "outputs": {
            "image_record": "image_record.json",
            "timeline": "timeline.json",
            "ocr": "raw_outputs/ocr.json",
            "normalized_image": "artifacts/normalized_image.jpg",
            "debug_overlay": "artifacts/debug_overlay.jpg",
        },
    }
    write_json(raw_dir / "ocr.json", ocr_payload)
    write_json(item_dir / "image_record.json", image_record)
    write_json(item_dir / "timeline.json", timeline)
    write_json(item_dir / "convert_info.json", convert_info)
    save_normalized_image(source, artifacts_dir / "normalized_image.jpg")
    save_debug_overlay(source, artifacts_dir / "debug_overlay.jpg", ocr_payload)
    return item_dir


def build_timeline(item: ImageSource, image_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_type": "image_timeline",
        "item_id": item.item_id,
        "source": {
            "path": item.source_path,
            "relative_path": item.relative_path,
            "sha256": item.sha256,
        },
        "events": [
            {
                "time": item.captured_at or item.modified_at,
                "type": "image_observed",
                "image_record_ref": "image_record.json",
                "summary": {
                    "image_kind": image_record["classification"]["image_kind"],
                    "content_types": image_record["classification"]["content_types"],
                    "has_text": image_record["text"]["has_text"],
                    "ocr_block_count": len(image_record["text"]["blocks"]),
                },
            }
        ],
    }


def create_download_zip(output_root: Path, item_dirs: list[Path]) -> Path | None:
    if not item_dirs:
        return None
    downloads = output_root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive_path = downloads / f"TimelineForImage-{now_iso().replace(':', '').replace('+', 'Z')}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", "# TimelineForImage Export\n\nOriginal image files are not included.\n")
        for item_dir in item_dirs:
            for name in ["convert_info.json", "timeline.json", "image_record.json"]:
                archive.write(item_dir / name, f"items/{item_dir.name}/{name}")
    return archive_path


def sync_latest(output_root: Path, archive_path: Path | None) -> None:
    latest = output_root / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    if archive_path and archive_path.exists():
        shutil.copyfile(archive_path, latest / "TimelineForImage-export.zip")


def write_status(run_dir: Path, status: RunStatus) -> None:
    write_json(run_dir / "status.json", status.to_dict())


def list_items(settings: Settings) -> list[dict[str, Any]]:
    catalog = load_catalog(internal_state_root())
    return sorted(catalog.get("items", {}).values(), key=lambda row: row.get("relative_path", ""))


def remove_items(settings: Settings, item_ids: list[str], dry_run: bool = False) -> dict[str, Any]:
    state_root = internal_state_root()
    catalog = load_catalog(state_root)
    records = catalog.get("items", {})
    requested = expand_item_ids(item_ids)
    if not requested:
        raise ValueError("No item IDs were specified.")
    removed: list[dict[str, Any]] = []
    missing: list[str] = []
    for item_id in requested:
        row = records.get(item_id)
        if not isinstance(row, dict):
            missing.append(item_id)
            continue
        output_dir = Path(str(row.get("output_dir") or ""))
        removed.append(
            {
                "item_id": item_id,
                "relative_path": row.get("relative_path"),
                "output_dir": str(output_dir),
                "output_dir_exists": output_dir.exists(),
            }
        )
        if dry_run:
            continue
        if output_dir.exists():
            shutil.rmtree(output_dir)
        remove_catalog_item(catalog, item_id)
    if not dry_run:
        save_catalog(state_root, catalog)
    return {
        "dry_run": dry_run,
        "requested_count": len(requested),
        "removed_count": len(removed),
        "missing_count": len(missing),
        "removed": removed,
        "missing": missing,
        "source_images_removed": False,
    }


def expand_item_ids(values: list[str]) -> list[str]:
    item_ids: list[str] = []
    for value in values:
        for part in str(value).split(","):
            stripped = part.strip()
            if stripped and stripped not in item_ids:
                item_ids.append(stripped)
    return item_ids


def list_runs(settings: Settings) -> list[dict[str, Any]]:
    runs_dir = internal_state_root() / "runs"
    rows = []
    if not runs_dir.exists():
        return rows
    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        result_path = run_dir / "result.json"
        status_path = run_dir / "status.json"
        rows.append(
            {
                "run_id": run_dir.name,
                "status": read_json(status_path) if status_path.exists() else None,
                "result": read_json(result_path) if result_path.exists() else None,
            }
        )
    return rows
