from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

from .discovery import discover_images
from .fs_utils import read_json, write_json
from .locks import exclusive_lock
from .model_inventory import list_models
from .processor import (
    OCR_MODE,
    REQUIRED_ITEM_FILES,
    cleanup_generated_artifacts,
    list_items,
    list_runs,
    refresh_items,
    remove_items,
)
from .settings import (
    Settings,
    internal_state_root,
    init_settings,
    load_settings,
    resolved_input_roots,
    resolved_output_root,
    resolve_local_path,
    save_settings,
    settings_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = dispatch_command(args)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if result is None:
        parser.error("Unsupported command.")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="timeline-for-image")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    sub = parser.add_subparsers(dest="command", required=True)

    add_settings_parser(sub)
    add_files_parser(sub)
    add_items_parser(sub)
    add_runs_parser(sub)
    add_models_parser(sub)
    add_serve_parser(sub)
    sub.add_parser("health")
    sub.add_parser("doctor")
    add_maintenance_parser(sub)

    return parser


def add_settings_parser(sub: Any) -> None:
    settings_parser = sub.add_parser("settings")
    settings_sub = settings_parser.add_subparsers(dest="settings_command", required=True)
    settings_sub.add_parser("init")
    settings_sub.add_parser("status")
    settings_save = settings_sub.add_parser("save")
    settings_save.add_argument("--input-root", action="append")
    settings_save.add_argument("--output-root")


def add_files_parser(sub: Any) -> None:
    files_parser = sub.add_parser("files")
    files_sub = files_parser.add_subparsers(dest="files_command", required=True)
    files_list_parser = files_sub.add_parser("list")
    add_paging_arguments(files_list_parser)


def add_items_parser(sub: Any) -> None:
    items_parser = sub.add_parser("items")
    items_sub = items_parser.add_subparsers(dest="items_command", required=True)
    refresh_parser = items_sub.add_parser("refresh")
    refresh_parser.add_argument("--max-items", type=int)
    refresh_parser.add_argument("--reprocess-duplicates", action="store_true")
    items_list_parser = items_sub.add_parser("list")
    add_paging_arguments(items_list_parser)
    download_parser = items_sub.add_parser("download")
    download_parser.add_argument("--item-id", action="append")
    download_parser.add_argument("--to")
    download_parser.add_argument("--overwrite", action="store_true")
    remove_parser = items_sub.add_parser("remove")
    remove_parser.add_argument("--item-id", action="append", default=[])
    remove_parser.add_argument("--dry-run", action="store_true")


def add_runs_parser(sub: Any) -> None:
    runs_parser = sub.add_parser("runs")
    runs_sub = runs_parser.add_subparsers(dest="runs_command", required=True)
    runs_list_parser = runs_sub.add_parser("list")
    add_paging_arguments(runs_list_parser)
    show_run = runs_sub.add_parser("show")
    show_run.add_argument("--run-id", required=True)


def add_models_parser(sub: Any) -> None:
    models_parser = sub.add_parser("models")
    models_sub = models_parser.add_subparsers(dest="models_command", required=True)
    models_sub.add_parser("list")


def add_serve_parser(sub: Any) -> None:
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--interval-seconds", type=float)
    serve_parser.add_argument("--max-items", type=int)
    serve_parser.add_argument("--once", action="store_true")


def add_maintenance_parser(sub: Any) -> None:
    maintenance_parser = sub.add_parser("maintenance")
    maintenance_sub = maintenance_parser.add_subparsers(dest="maintenance_command", required=True)
    cleanup_parser = maintenance_sub.add_parser("cleanup")
    cleanup_parser.add_argument("--keep-runs", type=int, default=100)
    cleanup_parser.add_argument("--keep-downloads", type=int, default=20)
    cleanup_parser.add_argument("--dry-run", action="store_true")


def dispatch_command(args: argparse.Namespace) -> int | None:
    enforce_docker_first()
    if args.command == "health":
        return handle_health(args)
    if args.command == "settings":
        return handle_settings(args)
    if args.command == "serve":
        return handle_serve(args)
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
    if args.command == "maintenance":
        return handle_maintenance(args, settings)
    return None


def enforce_docker_first() -> None:
    if os.environ.get("TIMELINE_FOR_IMAGE_IN_DOCKER") == "1":
        return
    if is_in_docker():
        return
    raise ValueError("Host CLI execution is disabled. Use .\\cli.ps1.")


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
            },
        }
        return emit(args, payload, format_settings_status(payload))
    if args.settings_command == "save":
        current = load_settings()
        updated = Settings(
            schema_version=current.schema_version,
            input_roots=args.input_root or current.input_roots,
            output_root=args.output_root or current.output_root,
        )
        save_settings(updated)
        return emit(args, {"settings": updated.__dict__}, "settings saved")
    raise ValueError("Unsupported settings command.")


def handle_serve(args: argparse.Namespace) -> int:
    interval_seconds = worker_interval_seconds(args.interval_seconds)
    while True:
        event: dict[str, Any]
        try:
            settings = load_settings()
            result = refresh_items(settings, max_items=args.max_items, reprocess_duplicates=False)
            event = {
                "event": "refresh_skipped_no_changes" if result["state"] == "skipped_no_changes" else "refresh_completed",
                "ok": result["failed_count"] == 0,
                "run_id": result["run_id"],
                "source_count": result["source_count"],
                "processed_count": result["processed_count"],
                "skipped_count": result["skipped_count"],
                "failed_count": result["failed_count"],
                "archive_path": result.get("archive_path"),
                "next_refresh_seconds": None if args.once else interval_seconds,
            }
            write_worker_event(args, event)
            if args.once:
                return 0 if event["ok"] else 1
        except Exception as exc:
            event = {
                "event": "refresh_failed",
                "ok": False,
                "error": str(exc),
                "next_refresh_seconds": None if args.once else interval_seconds,
            }
            write_worker_event(args, event)
            if args.once:
                return 1
        time.sleep(interval_seconds)


def worker_interval_seconds(value: float | None) -> float:
    if value is None:
        raw = os.environ.get("TIMELINE_FOR_IMAGE_WORKER_INTERVAL_SECONDS", "60")
        value = float(raw)
    if value <= 0:
        raise ValueError("Worker interval must be greater than 0 seconds.")
    return value


def write_worker_event(args: argparse.Namespace, event: dict[str, Any]) -> None:
    if args.json:
        print(json.dumps(event, ensure_ascii=False), flush=True)
        return
    if event["ok"]:
        print(
            "worker: "
            f"{event['event']} run_id={event.get('run_id') or 'none'} "
            f"processed={event.get('processed_count', 0)} "
            f"skipped={event.get('skipped_count', 0)} "
            f"failed={event.get('failed_count', 0)}",
            flush=True,
        )
    else:
        print(f"worker: {event['event']} error={event.get('error', 'unknown')}", file=sys.stderr, flush=True)


def handle_health(args: argparse.Namespace) -> int:
    state_root = internal_state_root()
    state_root.mkdir(parents=True, exist_ok=True)
    probe = state_root / f".healthcheck-{os.getpid()}.tmp"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink(missing_ok=True)
    state_check = path_check(state_root, needs_write=True)
    payload = {
        "ok": state_check["writable"],
        "state_root": state_check,
    }
    text = f"ok: {payload['ok']}\nstate_root: {state_check['path']} writable={state_check['writable']}"
    return emit(args, payload, text)


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
        archive = create_selected_download(settings, args.item_id or [], args.to, args.overwrite)
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


def handle_maintenance(args: argparse.Namespace, settings: Settings) -> int:
    if args.maintenance_command == "cleanup":
        result = cleanup_generated_artifacts(
            settings,
            keep_runs=args.keep_runs,
            keep_downloads=args.keep_downloads,
            dry_run=args.dry_run,
        )
        return emit(args, result, format_cleanup(result))
    raise ValueError("Unsupported maintenance command.")


def handle_doctor(args: argparse.Namespace, settings: Settings) -> int:
    payload = build_doctor_payload(settings)
    return emit(args, payload, format_doctor(payload))


def build_doctor_payload(settings: Settings) -> dict[str, Any]:
    input_roots = resolved_input_roots(settings)
    output_root = resolved_output_root(settings)
    state_root = internal_state_root()
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
    state_check = path_check(state_root, needs_write=True)
    ocr_check = doctor_ocr()
    validation = validate_settings(settings, input_checks, output_check, state_check, ocr_check)
    payload = {
        "settings_path": str(settings_path()),
        "settings_exists": settings_path().exists(),
        "input_roots": input_checks,
        "output_root": output_check,
        "state_root": state_check,
        "ocr": ocr_check,
        "validation": validation,
        "ok": validation["ok"],
    }
    return payload


def format_doctor(payload: dict[str, Any]) -> str:
    validation = payload["validation"]
    lines = [
        f"settings: {payload['settings_path']} exists={payload['settings_exists']}",
        *[
            f"input: {row['path']} exists={row['exists']} readable={row['readable']} supported_images={row['supported_image_count']}"
            for row in payload["input_roots"]
        ],
        f"output: {payload['output_root']['path']} writable={payload['output_root']['writable']}",
        f"state: {payload['state_root']['path']} writable={payload['state_root']['writable']}",
        f"ocr: mode={payload['ocr']['mode']} ready={payload['ocr']['ready']}",
        f"ok: {payload['ok']}",
    ]
    if validation["errors"]:
        lines.extend(["errors:", *[f"  - {error}" for error in validation["errors"]]])
    if validation["warnings"]:
        lines.extend(["warnings:", *[f"  - {warning}" for warning in validation["warnings"]]])
    return "\n".join(lines)


def doctor_ocr() -> dict[str, Any]:
    try:
        import pytesseract

        languages = sorted(pytesseract.get_languages(config=""))
        return {"mode": OCR_MODE, "ready": "jpn" in languages and "eng" in languages, "languages": languages}
    except Exception as exc:
        return {"mode": OCR_MODE, "ready": False, "languages": [], "warning": str(exc)}


def create_selected_download(
    settings: Settings,
    item_ids: list[str],
    destination: str | None = None,
    overwrite: bool = False,
) -> Path:
    with exclusive_lock(internal_state_root(), "catalog"):
        return create_selected_download_unlocked(settings, item_ids, destination, overwrite)


def create_selected_download_unlocked(
    settings: Settings,
    item_ids: list[str],
    destination: str | None = None,
    overwrite: bool = False,
) -> Path:
    rows = list_items(settings)
    selected_ids = set(expand_download_item_ids(item_ids))
    selected = rows if not selected_ids else [row for row in rows if row["item_id"] in selected_ids]
    if not selected:
        raise ValueError("No items selected for download.")
    output_root = resolved_output_root(settings)
    archive = resolve_download_destination(output_root, destination, overwrite)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", "# TimelineForImage selected export\n\nOriginal image files are not included.\n")
        for row in selected:
            item_dir = Path(row["output_dir"])
            for name in REQUIRED_ITEM_FILES:
                path = item_dir / name
                if not path.is_file():
                    raise FileNotFoundError(f"Item artifact does not exist: {path}")
                zf.write(path, f"items/{item_dir.name}/{name}")
    return archive


def expand_download_item_ids(values: list[str]) -> list[str]:
    item_ids: list[str] = []
    for value in values:
        for part in str(value).split(","):
            stripped = part.strip()
            if stripped and stripped not in item_ids:
                item_ids.append(stripped)
    return item_ids


def resolve_download_destination(output_root: Path, destination: str | None, overwrite: bool) -> Path:
    if destination and destination.strip():
        target = resolve_local_path(destination)
        archive = target if target.suffix.lower() == ".zip" else target / "TimelineForImage-selected.zip"
    else:
        archive = output_root / "downloads" / "TimelineForImage-selected.zip"
        overwrite = True
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists() and not overwrite:
        raise FileExistsError(f"Download target already exists: {archive}")
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
    state_check: dict[str, Any],
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
    if not state_check["writable"]:
        errors.append(f"State root is not writable: {state_check['path']}")
    if not ocr_check["ready"]:
        warnings.append(f"OCR backend is not ready for mode={OCR_MODE}.")
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


def format_cleanup(result: dict[str, Any]) -> str:
    rows = [
        f"dry_run: {result['dry_run']}",
        f"runs_kept: {result['runs']['kept_count']}",
        f"runs_removed: {result['runs']['removed_count']}",
        f"downloads_kept: {result['downloads']['kept_count']}",
        f"downloads_removed: {result['downloads']['removed_count']}",
    ]
    rows.extend(f"removed_run: {path}" for path in result["runs"]["removed"])
    rows.extend(f"removed_download: {path}" for path in result["downloads"]["removed"])
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
