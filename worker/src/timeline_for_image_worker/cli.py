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
from .processor import list_items, list_runs, refresh_items
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
    files_sub.add_parser("list")

    items_parser = sub.add_parser("items")
    items_sub = items_parser.add_subparsers(dest="items_command", required=True)
    refresh_parser = items_sub.add_parser("refresh")
    refresh_parser.add_argument("--max-items", type=int)
    refresh_parser.add_argument("--reprocess-duplicates", action="store_true")
    items_sub.add_parser("list")
    download_parser = items_sub.add_parser("download")
    download_parser.add_argument("--item-id", action="append")
    download_parser.add_argument("--all", action="store_true")

    runs_parser = sub.add_parser("runs")
    runs_sub = runs_parser.add_subparsers(dest="runs_command", required=True)
    runs_sub.add_parser("list")
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
        payload = {"count": len(items), "files": [item.to_dict() for item in items]}
        text = "\n".join(f"{item.item_id} {item.relative_path}" for item in items) or "No image files found."
        return emit(args, payload, text)
    raise ValueError("Unsupported files command.")


def handle_items(args: argparse.Namespace, settings: Settings) -> int:
    if args.items_command == "refresh":
        result = refresh_items(settings, max_items=args.max_items, reprocess_duplicates=args.reprocess_duplicates)
        return emit(args, result, format_refresh(result))
    if args.items_command == "list":
        rows = list_items(settings)
        return emit(args, {"count": len(rows), "items": rows}, "\n".join(f"{row['item_id']} {row['relative_path']}" for row in rows) or "No items.")
    if args.items_command == "download":
        archive = create_selected_download(settings, args.item_id or [], args.all)
        return emit(args, {"archive_path": str(archive)}, f"archive_path: {archive}")
    raise ValueError("Unsupported items command.")


def handle_runs(args: argparse.Namespace, settings: Settings) -> int:
    rows = list_runs(settings)
    if args.runs_command == "list":
        text = "\n".join(f"{row['run_id']} {((row.get('result') or {}).get('state') or 'unknown')}" for row in rows) or "No runs."
        return emit(args, {"runs": rows}, text)
    if args.runs_command == "show":
        for row in rows:
            if row["run_id"] == args.run_id:
                return emit(args, row, format_run(row))
        raise FileNotFoundError(f"Run not found: {args.run_id}")
    raise ValueError("Unsupported runs command.")


def handle_doctor(args: argparse.Namespace, settings: Settings) -> int:
    input_roots = resolved_input_roots(settings)
    output_root = resolved_output_root(settings)
    appdata_root = resolved_appdata_root(settings)
    payload = {
        "settings_path": str(settings_path()),
        "settings_exists": settings_path().exists(),
        "input_roots": [{"path": str(path), "exists": path.exists(), "readable": os.access(path, os.R_OK)} for path in input_roots],
        "output_root": {"path": str(output_root), "parent_writable": os.access(nearest_existing_parent(output_root), os.W_OK)},
        "appdata_root": {"path": str(appdata_root), "parent_writable": os.access(nearest_existing_parent(appdata_root), os.W_OK)},
        "ocr": doctor_ocr(settings.ocr_mode),
        "privacy_filter": settings.privacy_filter,
    }
    lines = [
        f"settings: {payload['settings_path']} exists={payload['settings_exists']}",
        *[f"input: {row['path']} exists={row['exists']} readable={row['readable']}" for row in payload["input_roots"]],
        f"output: {payload['output_root']['path']} parent_writable={payload['output_root']['parent_writable']}",
        f"appdata: {payload['appdata_root']['path']} parent_writable={payload['appdata_root']['parent_writable']}",
        f"ocr: mode={payload['ocr']['mode']} ready={payload['ocr']['ready']}",
        f"privacy_filter: {payload['privacy_filter']}",
    ]
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


def nearest_existing_parent(path: Path) -> Path:
    current = path if path.exists() else path.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


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


def format_run(row: dict[str, Any]) -> str:
    result = row.get("result") or {}
    return "\n".join([f"run_id: {row['run_id']}", f"state: {result.get('state', 'unknown')}", f"processed_count: {result.get('processed_count', 0)}"])


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
