from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any

from .discovery import discover_images
from .fs_utils import read_json, write_json
from .model_inventory import list_models
from .processor import list_items, list_runs, refresh_items, remove_items
from .settings import (
    Settings,
    init_settings,
    load_settings,
    resolved_appdata_root,
    resolved_input_roots,
    resolved_output_root,
    save_settings,
    settings_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="timeline-for-image")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    sub = parser.add_subparsers(dest="command", required=True)

    settings_parser = sub.add_parser("settings")
    settings_sub = settings_parser.add_subparsers(dest="settings_command", required=True)
    settings_sub.add_parser("init")
    settings_sub.add_parser("status")
    settings_save = settings_sub.add_parser("save")
    settings_save.add_argument("--input-root", action="append")
    settings_save.add_argument("--output-root")
    settings_save.add_argument("--appdata-root")
    settings_save.add_argument("--compute-mode", choices=("cpu", "gpu"))
    settings_save.add_argument("--ocr-mode", choices=("off", "auto", "always", "mock"))

    files_parser = sub.add_parser("files")
    files_sub = files_parser.add_subparsers(dest="files_command", required=True)
    files_list_parser = files_sub.add_parser("list")
    add_paging_arguments(files_list_parser)

    items_parser = sub.add_parser("items")
    items_sub = items_parser.add_subparsers(dest="items_command", required=True)
    refresh_parser = items_sub.add_parser("refresh")
    refresh_parser.add_argument("--max-items", type=int)
    refresh_parser.add_argument("--reprocess-duplicates", action="store_true")
    items_list_parser = items_sub.add_parser("list")
    add_paging_arguments(items_list_parser)
    download_parser = items_sub.add_parser("download")
    download_parser.add_argument("--item-id", action="append")
    download_parser.add_argument("--all", action="store_true")
    remove_parser = items_sub.add_parser("remove")
    remove_parser.add_argument("--item-id", action="append", default=[])
    remove_parser.add_argument("--dry-run", action="store_true")

    runs_parser = sub.add_parser("runs")
    runs_sub = runs_parser.add_subparsers(dest="runs_command", required=True)
    runs_list_parser = runs_sub.add_parser("list")
    add_paging_arguments(runs_list_parser)
    show_run = runs_sub.add_parser("show")
    show_run.add_argument("--run-id", required=True)

    models_parser = sub.add_parser("models")
    models_sub = models_parser.add_subparsers(dest="models_command", required=True)
    models_sub.add_parser("list")

    sub.add_parser("doctor")

    args = parser.parse_args(argv)
    try:
        enforce_docker_first()
        if args.command == "settings":
            return handle_settings(args)
        settings = load_settings()
        if args.command == "files":
            return handle_files(args, settings)
        if args.command == "items":
            return handle_items(args, settings)
        if args.command == "runs":
            return handle_runs(args, settings)
        if args.command == "models":
            return emit(args, {"models": list_models()}, format_models(list_models()))
        if args.command == "doctor":
            return handle_doctor(args, settings)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    parser.error("Unsupported command.")
    return 2


def enforce_docker_first() -> None:
    if os.environ.get("TIMELINE_FOR_IMAGE_IN_DOCKER") == "1":
        return
    if os.environ.get("TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI") == "1":
        return
    if is_in_docker():
        return
    raise ValueError("Host CLI execution is disabled. Use .\\cli.ps1, or set TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI=1 only for tests.")


def is_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def add_paging_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=50)


def handle_settings(args: argparse.Namespace) -> int:
    if args.settings_command == "init":
        created, path = init_settings()
        return emit(args, {"created": created, "settings_path": str(path)}, f"{'created' if created else 'exists'}: {path}")
    if args.settings_command == "status":
        settings = load_settings()
        payload = {
            "settings_path": str(settings_path()),
            "settings": settings.__dict__,
            "resolved": {
                "input_roots": [str(path) for path in resolved_input_roots(settings)],
                "output_root": str(resolved_output_root(settings)),
                "appdata_root": str(resolved_appdata_root(settings)),
            },
        }
        return emit(args, payload, format_settings_status(payload))
    if args.settings_command == "save":
        current = load_settings()
        updated = Settings(
            schema_version=current.schema_version,
            input_roots=args.input_root or current.input_roots,
            output_root=args.output_root or current.output_root,
            appdata_root=args.appdata_root or current.appdata_root,
            compute_mode=args.compute_mode or current.compute_mode,
            ocr_mode=args.ocr_mode or current.ocr_mode,
            privacy_filter="none",
        )
        save_settings(updated)
        return emit(args, {"settings": updated.__dict__}, "settings saved")
    raise ValueError("Unsupported settings command.")


def handle_files(args: argparse.Namespace, settings: Settings) -> int:
    if args.files_command == "list":
        items = discover_images(resolved_input_roots(settings))
        page = paginate([item.to_dict() for item in items], args.page, args.page_size)
        payload = {"count": len(items), **page, "files": page["items"]}
        payload.pop("items")
        text_rows = [f"{row['item_id']} {row['relative_path']}" for row in payload["files"]]
        text = "\n".join([format_page_summary(payload), *text_rows]) if text_rows else "No image files found."
        return emit(args, payload, text)
    raise ValueError("Unsupported files command.")


def handle_items(args: argparse.Namespace, settings: Settings) -> int:
    if args.items_command == "refresh":
        result = refresh_items(settings, max_items=args.max_items, reprocess_duplicates=args.reprocess_duplicates)
        return emit(args, result, format_refresh(result))
    if args.items_command == "list":
        rows = list_items(settings)
        page = paginate(rows, args.page, args.page_size)
        payload = {"count": len(rows), **page}
        text_rows = [f"{row['item_id']} {row['relative_path']}" for row in payload["items"]]
        text = "\n".join([format_page_summary(payload), *text_rows]) if text_rows else "No items."
        return emit(args, payload, text)
    if args.items_command == "download":
        archive = create_selected_download(settings, args.item_id or [], args.all)
        return emit(args, {"archive_path": str(archive)}, f"archive_path: {archive}")
    if args.items_command == "remove":
        result = remove_items(settings, args.item_id, dry_run=args.dry_run)
        return emit(args, result, format_remove(result))
    raise ValueError("Unsupported items command.")


def handle_runs(args: argparse.Namespace, settings: Settings) -> int:
    rows = list_runs(settings)
    if args.runs_command == "list":
        page = paginate(rows, args.page, args.page_size)
        payload = {"count": len(rows), **page}
        payload["runs"] = payload.pop("items")
        text_rows = [f"{row['run_id']} {((row.get('result') or {}).get('state') or 'unknown')}" for row in payload["runs"]]
        text = "\n".join([format_page_summary(payload), *text_rows]) if text_rows else "No runs."
        return emit(args, payload, text)
    if args.runs_command == "show":
        for row in rows:
            if row["run_id"] == args.run_id:
                detail = enrich_run_detail(row)
                return emit(args, detail, format_run(detail))
        raise FileNotFoundError(f"Run not found: {args.run_id}")
    raise ValueError("Unsupported runs command.")


def handle_doctor(args: argparse.Namespace, settings: Settings) -> int:
    input_roots = resolved_input_roots(settings)
    output_root = resolved_output_root(settings)
    appdata_root = resolved_appdata_root(settings)
    input_checks = [
        {
            "path": str(path),
            "exists": path.exists(),
            "readable": os.access(path, os.R_OK),
            "supported_image_count": len(discover_images([path])) if path.exists() and os.access(path, os.R_OK) else 0,
        }
        for path in input_roots
    ]
    output_check = path_check(output_root, needs_write=True)
    appdata_check = path_check(appdata_root, needs_write=True)
    ocr_check = doctor_ocr(settings.ocr_mode)
    validation = validate_settings(settings, input_checks, output_check, appdata_check, ocr_check)
    payload = {
        "settings_path": str(settings_path()),
        "settings_exists": settings_path().exists(),
        "input_roots": input_checks,
        "output_root": output_check,
        "appdata_root": appdata_check,
        "ocr": ocr_check,
        "privacy_filter": settings.privacy_filter,
        "validation": validation,
        "ok": validation["ok"],
    }
    lines = [
        f"settings: {payload['settings_path']} exists={payload['settings_exists']}",
        *[
            f"input: {row['path']} exists={row['exists']} readable={row['readable']} supported_images={row['supported_image_count']}"
            for row in payload["input_roots"]
        ],
        f"output: {payload['output_root']['path']} writable={payload['output_root']['writable']}",
        f"appdata: {payload['appdata_root']['path']} writable={payload['appdata_root']['writable']}",
        f"ocr: mode={payload['ocr']['mode']} ready={payload['ocr']['ready']}",
        f"privacy_filter: {payload['privacy_filter']}",
        f"ok: {payload['ok']}",
    ]
    if validation["errors"]:
        lines.extend(["errors:", *[f"  - {error}" for error in validation["errors"]]])
    if validation["warnings"]:
        lines.extend(["warnings:", *[f"  - {warning}" for warning in validation["warnings"]]])
    return emit(args, payload, "\n".join(lines))


def doctor_ocr(mode: str) -> dict[str, Any]:
    if mode in {"off", "mock"}:
        return {"mode": mode, "ready": True, "languages": []}
    try:
        import pytesseract

        languages = sorted(pytesseract.get_languages(config=""))
        return {"mode": mode, "ready": "jpn" in languages and "eng" in languages, "languages": languages}
    except Exception as exc:
        return {"mode": mode, "ready": False, "languages": [], "warning": str(exc)}


def create_selected_download(settings: Settings, item_ids: list[str], all_items: bool) -> Path:
    rows = list_items(settings)
    selected = rows if all_items else [row for row in rows if row["item_id"] in set(item_ids)]
    if not selected:
        raise ValueError("No items selected for download.")
    output_root = resolved_output_root(settings)
    downloads = output_root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / "TimelineForImage-selected.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", "# TimelineForImage selected export\n\nOriginal image files are not included.\n")
        for row in selected:
            item_dir = Path(row["output_dir"])
            for name in ["convert_info.json", "timeline.json", "image_record.json"]:
                zf.write(item_dir / name, f"items/{item_dir.name}/{name}")
    return archive


def path_check(path: Path, needs_write: bool) -> dict[str, Any]:
    nearest_parent = nearest_existing_parent(path)
    exists = path.exists()
    writable = os.access(path, os.W_OK) if exists else os.access(nearest_parent, os.W_OK)
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": path.is_dir() if exists else False,
        "nearest_existing_parent": str(nearest_parent),
        "parent_writable": os.access(nearest_parent, os.W_OK),
        "writable": writable if needs_write else None,
    }


def validate_settings(
    settings: Settings,
    input_checks: list[dict[str, Any]],
    output_check: dict[str, Any],
    appdata_check: dict[str, Any],
    ocr_check: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not settings.input_roots:
        errors.append("inputRoots is empty.")
    for row in input_checks:
        if not row["exists"]:
            errors.append(f"Input root does not exist: {row['path']}")
        elif not row["readable"]:
            errors.append(f"Input root is not readable: {row['path']}")
        elif row["supported_image_count"] == 0:
            warnings.append(f"Input root has no supported image files: {row['path']}")
    if not output_check["writable"]:
        errors.append(f"Output root is not writable: {output_check['path']}")
    if not appdata_check["writable"]:
        errors.append(f"Appdata root is not writable: {appdata_check['path']}")
    if settings.privacy_filter != "none":
        errors.append("privacyFilter must be 'none' in the local-only product profile.")
    if settings.ocr_mode not in {"off", "auto", "always", "mock"}:
        errors.append(f"Unsupported ocrMode: {settings.ocr_mode}")
    if not ocr_check["ready"]:
        warnings.append(f"OCR backend is not ready for mode={settings.ocr_mode}.")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def nearest_existing_parent(path: Path) -> Path:
    current = path if path.exists() else path.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def paginate(rows: list[Any], page: int, page_size: int) -> dict[str, Any]:
    if page < 1:
        raise ValueError("--page must be greater than or equal to 1.")
    if page_size < 1:
        raise ValueError("--page-size must be greater than or equal to 1.")
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    page_count = max(1, (total + page_size - 1) // page_size)
    return {
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "items": rows[start:end],
    }


def format_page_summary(payload: dict[str, Any]) -> str:
    return f"count: {payload['count']} page: {payload['page']}/{payload['page_count']} page_size: {payload['page_size']}"


def enrich_run_detail(row: dict[str, Any]) -> dict[str, Any]:
    result = row.get("result") or {}
    items = []
    for item in result.get("items", []):
        output_dir = Path(str(item.get("output_dir") or ""))
        artifacts = {
            "output_dir_exists": output_dir.exists(),
            "convert_info": str(output_dir / "convert_info.json"),
            "timeline": str(output_dir / "timeline.json"),
            "image_record": str(output_dir / "image_record.json"),
        }
        items.append({**item, "artifacts": artifacts})
    return {**row, "items": items}


def format_settings_status(payload: dict[str, Any]) -> str:
    settings = payload["settings"]
    resolved = payload["resolved"]
    return "\n".join(
        [
            f"settings_path: {payload['settings_path']}",
            f"input_roots: {', '.join(settings['input_roots'])}",
            f"output_root: {settings['output_root']}",
            f"appdata_root: {settings['appdata_root']}",
            f"ocr_mode: {settings['ocr_mode']}",
            f"privacy_filter: {settings['privacy_filter']}",
            f"resolved_output_root: {resolved['output_root']}",
        ]
    )


def format_refresh(result: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"run_id: {result['run_id']}",
            f"state: {result['state']}",
            f"source_count: {result['source_count']}",
            f"processed_count: {result['processed_count']}",
            f"skipped_count: {result['skipped_count']}",
            f"failed_count: {result['failed_count']}",
            f"archive_path: {result.get('archive_path') or 'none'}",
        ]
    )


def format_remove(result: dict[str, Any]) -> str:
    rows = [
        f"dry_run: {result['dry_run']}",
        f"requested_count: {result['requested_count']}",
        f"removed_count: {result['removed_count']}",
        f"missing_count: {result['missing_count']}",
        "source_images_removed: False",
    ]
    rows.extend(f"removed: {row['item_id']} {row.get('relative_path')}" for row in result["removed"])
    rows.extend(f"missing: {item_id}" for item_id in result["missing"])
    return "\n".join(rows)


def format_run(row: dict[str, Any]) -> str:
    result = row.get("result") or {}
    return "\n".join(
        [
            f"run_id: {row['run_id']}",
            f"state: {result.get('state', 'unknown')}",
            f"source_count: {result.get('source_count', 0)}",
            f"processed_count: {result.get('processed_count', 0)}",
            f"skipped_count: {result.get('skipped_count', 0)}",
            f"failed_count: {result.get('failed_count', 0)}",
            f"archive_path: {result.get('archive_path') or 'none'}",
        ]
    )


def format_models(models: list[dict[str, object]]) -> str:
    return "\n".join(f"{model['id']} role={model['role']} local={model['local']}" for model in models)


def emit(args: argparse.Namespace, payload: Any, text: str) -> int:
    if args.json:
        write_json_to_stdout(payload)
    else:
        print(text)
    return 0


def write_json_to_stdout(payload: Any) -> None:
    import json

    print(json.dumps(payload, ensure_ascii=False, indent=2))
