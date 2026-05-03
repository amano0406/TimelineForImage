from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .catalog import load_catalog, needs_processing, remove_catalog_item, save_catalog, update_catalog_item
from .contracts import ImageSource, RunStatus
from .discovery import discover_images
from .fs_utils import now_iso, read_json, write_json
from .image_record import build_image_record, save_debug_overlay, save_normalized_image
from .locks import exclusive_lock
from .ocr import run_ocr
from .settings import Settings, internal_state_root, resolved_input_roots, resolved_output_root

OCR_MODE = "auto"
REQUIRED_ITEM_FILES = ("convert_info.json", "timeline.json", "image_record.json")


def refresh_items(settings: Settings, max_items: int | None = None, reprocess_duplicates: bool = False) -> dict[str, Any]:
    state_root = internal_state_root()
    with exclusive_lock(state_root, "catalog"):
        return refresh_items_unlocked(settings, max_items=max_items, reprocess_duplicates=reprocess_duplicates)


def refresh_items_unlocked(settings: Settings, max_items: int | None = None, reprocess_duplicates: bool = False) -> dict[str, Any]:
    state_root = internal_state_root()
    output_root = resolved_output_root(settings)
    state_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    sources = discover_images(resolved_input_roots(settings))
    catalog = load_catalog(state_root)
    candidates = [item for item in sources if needs_processing(catalog, item, reprocess_duplicates, output_root)]
    if max_items is not None:
        candidates = candidates[:max_items]
    if not candidates:
        return {
            "schema_version": 1,
            "run_id": None,
            "state": "skipped_no_changes",
            "source_count": len(sources),
            "processed_count": 0,
            "skipped_count": len(sources),
            "failed_count": 0,
            "archive_path": None,
            "items": [],
        }

    run_id = unique_artifact_id("run")
    run_dir = state_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_status(run_dir, RunStatus(run_id=run_id, state="running", current_stage="discover", started_at=now_iso(), updated_at=now_iso()))
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
    archive_path = downloads / f"TimelineForImage-{unique_artifact_id('export')}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", "# TimelineForImage Export\n\nOriginal image files are not included.\n")
        for item_dir in item_dirs:
            for name in REQUIRED_ITEM_FILES:
                archive.write(item_dir / name, f"items/{item_dir.name}/{name}")
    return archive_path


def sync_latest(output_root: Path, archive_path: Path | None) -> None:
    latest = output_root / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    if archive_path and archive_path.exists():
        shutil.copyfile(archive_path, latest / "TimelineForImage-export.zip")


def unique_artifact_id(prefix: str) -> str:
    timestamp = now_iso().replace(":", "").replace("+", "Z")
    return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"


def write_status(run_dir: Path, status: RunStatus) -> None:
    write_json(run_dir / "status.json", status.to_dict())


def list_items(settings: Settings) -> list[dict[str, Any]]:
    catalog = load_catalog(internal_state_root())
    output_root = resolved_output_root(settings)
    rows = [
        row
        for row in catalog.get("items", {}).values()
        if isinstance(row, dict) and catalog_row_matches_current_output(row, output_root)
    ]
    return sorted(rows, key=lambda row: row.get("relative_path", ""))


def catalog_row_matches_current_output(row: dict[str, Any], output_root: Path) -> bool:
    output_dir = Path(str(row.get("output_dir") or ""))
    if not is_path_under_root(output_dir, output_root):
        return False
    return item_output_complete(output_dir)


def item_output_complete(output_dir: Path) -> bool:
    return output_dir.is_dir() and all((output_dir / name).is_file() for name in REQUIRED_ITEM_FILES)


def is_path_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def remove_items(settings: Settings, item_ids: list[str], dry_run: bool = False) -> dict[str, Any]:
    state_root = internal_state_root()
    with exclusive_lock(state_root, "catalog"):
        return remove_items_unlocked(settings, item_ids, dry_run=dry_run)


def remove_items_unlocked(settings: Settings, item_ids: list[str], dry_run: bool = False) -> dict[str, Any]:
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


def cleanup_generated_artifacts(
    settings: Settings,
    keep_runs: int = 100,
    keep_downloads: int = 20,
    dry_run: bool = False,
) -> dict[str, Any]:
    if keep_runs < 0:
        raise ValueError("--keep-runs must be greater than or equal to 0.")
    if keep_downloads < 0:
        raise ValueError("--keep-downloads must be greater than or equal to 0.")

    state_root = internal_state_root()
    with exclusive_lock(state_root, "catalog"):
        return cleanup_generated_artifacts_unlocked(settings, keep_runs, keep_downloads, dry_run)


def cleanup_generated_artifacts_unlocked(
    settings: Settings,
    keep_runs: int,
    keep_downloads: int,
    dry_run: bool,
) -> dict[str, Any]:
    runs_dir = internal_state_root() / "runs"
    output_root = resolved_output_root(settings)
    run_candidates = sorted(
        [path for path in runs_dir.iterdir() if path.is_dir() and not path.is_symlink()] if runs_dir.exists() else [],
        key=lambda path: path.name,
        reverse=True,
    )
    download_candidates = sorted(
        generated_download_candidates(output_root / "downloads"),
        key=lambda path: (safe_mtime(path), path.name),
        reverse=True,
    )
    runs_to_remove = run_candidates[keep_runs:]
    downloads_to_remove = download_candidates[keep_downloads:]

    if not dry_run:
        for path in runs_to_remove:
            shutil.rmtree(path)
        for path in downloads_to_remove:
            path.unlink()

    return {
        "dry_run": dry_run,
        "runs": {
            "root": str(runs_dir),
            "candidate_count": len(run_candidates),
            "kept_count": len(run_candidates) - len(runs_to_remove),
            "removed_count": len(runs_to_remove),
            "removed": [str(path) for path in runs_to_remove],
        },
        "downloads": {
            "root": str(output_root / "downloads"),
            "candidate_count": len(download_candidates),
            "kept_count": len(download_candidates) - len(downloads_to_remove),
            "removed_count": len(downloads_to_remove),
            "removed": [str(path) for path in downloads_to_remove],
        },
    }


def generated_download_candidates(downloads_dir: Path) -> list[Path]:
    if not downloads_dir.exists():
        return []
    return [
        path
        for path in downloads_dir.glob("TimelineForImage-*.zip")
        if path.is_file() and path.name != "TimelineForImage-selected.zip"
    ]


def safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


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
