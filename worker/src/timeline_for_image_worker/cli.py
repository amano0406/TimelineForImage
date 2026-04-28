from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .captioning import check_local_caption_backend
from .catalog_store import build_processing_profile, compare_items
from .config import config_sources, load_config, merge_config, nested_value
from .contracts import JobRequest
from .discovery import SourceSpec, discover_image_sources
from .fs_utils import now_iso, read_json
from .job_store import (
    create_job,
    create_job_id,
    iter_run_dirs,
    load_request,
    load_status,
    result_path,
)
from .ocr import resolve_ocr_model
from .output_sync import sync_latest_output
from .processor import process_job
from .settings import init_settings, load_runtime_paths, load_settings, path_from_user_value, settings_path
from .sources import add_source, load_sources, remove_source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="timeline-for-image-worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    discover_parser = subparsers.add_parser("discover")
    _add_source_arguments(discover_parser)
    discover_parser.add_argument("--format", choices=("text", "json"), default="text")

    create_parser = subparsers.add_parser("create-job")
    _add_source_arguments(create_parser)
    create_parser.add_argument("--format", choices=("text", "json"), default="text")

    run_parser = subparsers.add_parser("run")
    _add_source_arguments(run_parser)
    run_parser.add_argument("--format", choices=("text", "json"), default="text")

    watch_parser = subparsers.add_parser("watch")
    _add_source_arguments(watch_parser)
    watch_parser.add_argument("--interval-seconds", type=float)
    watch_parser.add_argument("--min-quiet-seconds", type=float)
    watch_parser.add_argument("--once", action="store_true")
    watch_parser.add_argument("--format", choices=("text", "json"), default="text")

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--config")
    doctor_parser.add_argument("--caption-model")
    doctor_parser.add_argument("--format", choices=("text", "json"), default="text")

    settings_parser = subparsers.add_parser("settings")
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command", required=True)
    settings_init_parser = settings_subparsers.add_parser("init")
    settings_init_parser.add_argument("--format", choices=("text", "json"), default="text")

    sources_parser = subparsers.add_parser("sources")
    sources_subparsers = sources_parser.add_subparsers(dest="sources_command", required=True)
    sources_list_parser = sources_subparsers.add_parser("list")
    sources_list_parser.add_argument("--format", choices=("text", "json"), default="text")
    sources_add_parser = sources_subparsers.add_parser("add")
    sources_add_parser.add_argument("path")
    sources_add_parser.add_argument("--no-recursive", action="store_true")
    sources_add_parser.add_argument("--format", choices=("text", "json"), default="text")
    sources_remove_parser = sources_subparsers.add_parser("remove")
    sources_remove_parser.add_argument("path")
    sources_remove_parser.add_argument("--format", choices=("text", "json"), default="text")

    list_parser = subparsers.add_parser("list-jobs")
    list_parser.add_argument("--format", choices=("text", "json"), default="text")

    show_parser = subparsers.add_parser("show-job")
    show_parser.add_argument("job")
    show_parser.add_argument("--format", choices=("text", "json"), default="text")

    process_parser = subparsers.add_parser("process-job")
    process_parser.add_argument("job_dir")

    args = parser.parse_args(argv)
    try:
        _enforce_execution_environment()
        if args.command == "settings":
            return _handle_settings(args)
        args.config_payload = merge_config(load_settings(), _load_explicit_config(args))
        runtime = load_runtime_paths(args.config_payload)
        if args.command == "discover":
            return _handle_discover(args, runtime.state_root)
        if args.command == "create-job":
            return _handle_create_job(args, runtime.outputs_root, runtime.state_root)
        if args.command == "run":
            return _handle_run(args, runtime.outputs_root, runtime.state_root)
        if args.command == "watch":
            return _handle_watch(args, runtime.outputs_root, runtime.state_root)
        if args.command == "doctor":
            return _handle_doctor(args, runtime)
        if args.command == "sources":
            return _handle_sources(args, runtime.state_root)
        if args.command == "list-jobs":
            return _handle_list_jobs(args, runtime.outputs_root)
        if args.command == "show-job":
            return _handle_show_job(args, runtime.outputs_root)
        if args.command == "process-job":
            process_job(Path(args.job_dir).resolve(), runtime.state_root)
            return 0
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    parser.error("Unsupported command.")
    return 2


def _load_explicit_config(args: argparse.Namespace) -> dict[str, Any]:
    config_path = getattr(args, "config", None)
    if not config_path:
        return {}
    return load_config(str(path_from_user_value(config_path)))


def _enforce_execution_environment() -> None:
    if _host_cli_allowed():
        return
    raise ValueError(
        "Host CLI execution is disabled for TimelineForImage. "
        "Use `docker compose --profile worker run --rm worker ...`, "
        "or set TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI=1 only for tests."
    )


def _host_cli_allowed() -> bool:
    return (
        os.environ.get("TIMELINE_FOR_IMAGE_IN_DOCKER") == "1"
        or os.environ.get("TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI") == "1"
        or _is_running_in_docker()
    )


def _is_running_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config")
    parser.add_argument("--directory", action="append", default=[])
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--no-recursive", action="store_true")
    mock_group = parser.add_mutually_exclusive_group()
    mock_group.add_argument("--mock", dest="mock", action="store_true", default=None)
    mock_group.add_argument("--no-mock", dest="mock", action="store_false")
    parser.add_argument("--caption-mode", choices=("off", "mock", "local", "openai"))
    parser.add_argument("--caption-model")
    parser.add_argument("--ocr-mode", choices=("off", "mock", "auto", "always"))
    parser.add_argument("--ocr-model")
    parser.add_argument("--annotations-file")


def _handle_discover(args: argparse.Namespace, state_root: Path) -> int:
    source_specs = _resolve_source_specs(args, state_root)
    items = discover_image_sources(source_specs, mock=_effective_mock(args))
    payload = {"image_count": len(items), "items": [item.to_dict() for item in items]}
    text = "\n".join([f"image_count: {len(items)}", *[f"- {item.timeline_at} {item.relative_path}" for item in items]])
    _print_output(args.format, payload, text)
    return 0


def _handle_create_job(args: argparse.Namespace, outputs_root: Path, state_root: Path) -> int:
    request, job_dir = _prepare_job(args, outputs_root, state_root)
    payload = {
        "job_id": request.job_id,
        "run_directory": str(job_dir),
        "image_count": len(request.items),
        "reuse_summary": request.reuse_summary,
    }
    _print_output(
        args.format,
        payload,
        "\n".join([f"job_id: {request.job_id}", f"run_directory: {job_dir}", f"image_count: {len(request.items)}"]),
    )
    return 0


def _handle_run(args: argparse.Namespace, outputs_root: Path, state_root: Path) -> int:
    request, job_dir = _prepare_job(args, outputs_root, state_root, run_reason="manual")
    process_job(job_dir, state_root)
    latest = sync_latest_output(job_dir, outputs_root)
    result = read_json(result_path(job_dir))
    payload = {
        "job_id": request.job_id,
        "run_directory": str(job_dir),
        "state": result["state"],
        "archive_path": result["archive_path"],
        "latest_directory": latest["latest_directory"],
        "latest_archive_path": latest["latest_archive_path"],
        "image_count": result["image_count"],
        "caption_count": result.get("caption_count", 0),
        "ocr_count": result.get("ocr_count", 0),
        "ocr_ran_count": result.get("ocr_ran_count", 0),
        "visual_observation_count": result.get("visual_observation_count", 0),
        "timeline_group_count": result.get("timeline_group_count", 0),
        "annotation_count": result.get("annotation_count", 0),
        "derived_cache_hit_count": result.get("derived_cache_hit_count", 0),
        "derived_cache_miss_count": result.get("derived_cache_miss_count", 0),
        "reused_caption_count": result.get("reused_caption_count", 0),
        "generated_caption_count": result.get("generated_caption_count", 0),
        "reused_ocr_count": result.get("reused_ocr_count", 0),
        "generated_ocr_count": result.get("generated_ocr_count", 0),
        "reuse_summary": result.get("reuse_summary", {}),
    }
    _print_output(
        args.format,
        payload,
        "\n".join(
            [
                f"job_id: {request.job_id}",
                f"run_directory: {job_dir}",
                f"state: {result['state']}",
                f"archive_path: {result['archive_path']}",
                f"latest_directory: {payload['latest_directory']}",
                f"latest_archive_path: {payload['latest_archive_path']}",
                f"image_count: {result['image_count']}",
                f"caption_count: {payload['caption_count']}",
                f"ocr_count: {payload['ocr_count']}",
                f"ocr_ran_count: {payload['ocr_ran_count']}",
                f"visual_observation_count: {payload['visual_observation_count']}",
                f"timeline_group_count: {payload['timeline_group_count']}",
                f"annotation_count: {payload['annotation_count']}",
                f"derived_cache_hit_count: {payload['derived_cache_hit_count']}",
                f"derived_cache_miss_count: {payload['derived_cache_miss_count']}",
                f"reused_caption_count: {payload['reused_caption_count']}",
                f"generated_caption_count: {payload['generated_caption_count']}",
                f"reused_ocr_count: {payload['reused_ocr_count']}",
                f"generated_ocr_count: {payload['generated_ocr_count']}",
                f"new: {payload['reuse_summary'].get('new', 0)}",
                f"changed: {payload['reuse_summary'].get('changed', 0)}",
                f"unchanged: {payload['reuse_summary'].get('unchanged', 0)}",
            ]
        ),
    )
    return 0


def _handle_watch(args: argparse.Namespace, outputs_root: Path, state_root: Path) -> int:
    interval_seconds = _effective_interval_seconds(args)
    min_quiet_seconds = _effective_min_quiet_seconds(args)
    if interval_seconds <= 0:
        raise ValueError("--interval-seconds must be greater than zero.")
    if min_quiet_seconds < 0:
        raise ValueError("--min-quiet-seconds must be zero or greater.")
    while True:
        payload = _watch_cycle(args, outputs_root, state_root, min_quiet_seconds)
        _print_output(args.format, payload, _format_watch_text(payload))
        if args.once:
            return 0
        time.sleep(interval_seconds)


def _watch_cycle(args: argparse.Namespace, outputs_root: Path, state_root: Path, min_quiet_seconds: float) -> dict[str, Any]:
    source_specs = _resolve_source_specs(args, state_root)
    source_paths = [path for path, _ in source_specs]
    recursive = _source_specs_recursive_summary(source_specs)
    items = discover_image_sources(source_specs, mock=_effective_mock(args))
    if not items:
        return {"state": "skipped", "reason": "no_supported_images", "image_count": 0}
    if not _items_are_quiet(items, min_quiet_seconds):
        return {
            "state": "skipped",
            "reason": "waiting_for_quiet_period",
            "image_count": len(items),
            "min_quiet_seconds": min_quiet_seconds,
        }
    processing_profile = build_processing_profile(
        _effective_caption_mode(args),
        _effective_caption_model(args),
        _effective_ocr_mode(args),
        _effective_ocr_model(args),
    )
    reuse_summary = compare_items(state_root, items, processing_profile)
    if reuse_summary.get("new", 0) == 0 and reuse_summary.get("changed", 0) == 0:
        return {
            "state": "skipped",
            "reason": "no_changes",
            "image_count": len(items),
            "reuse_summary": reuse_summary,
        }

    run_reason = _watch_run_reason(reuse_summary)
    request, job_dir = _create_job_request(args, outputs_root, source_specs, items, processing_profile, reuse_summary, run_reason)
    process_job(job_dir, state_root)
    latest = sync_latest_output(job_dir, outputs_root)
    result = read_json(result_path(job_dir))
    return {
        "state": "ran",
        "reason": run_reason,
        "job_id": request.job_id,
        "run_directory": str(job_dir),
        "archive_path": result["archive_path"],
        "latest_directory": latest["latest_directory"],
        "latest_archive_path": latest["latest_archive_path"],
        "image_count": result["image_count"],
        "reuse_summary": result.get("reuse_summary", {}),
        "derived_cache_hit_count": result.get("derived_cache_hit_count", 0),
        "derived_cache_miss_count": result.get("derived_cache_miss_count", 0),
    }


def _items_are_quiet(items: list, min_quiet_seconds: float) -> bool:
    if min_quiet_seconds <= 0:
        return True
    now = time.time()
    for item in items:
        try:
            if now - Path(item.source_path).stat().st_mtime < min_quiet_seconds:
                return False
        except OSError:
            return False
    return True


def _watch_run_reason(reuse_summary: dict[str, int]) -> str:
    if reuse_summary.get("new", 0) and reuse_summary.get("changed", 0):
        return "watch:new-and-changed"
    if reuse_summary.get("new", 0):
        return "watch:new-file"
    return "watch:changed-file"


def _format_watch_text(payload: dict[str, Any]) -> str:
    if payload.get("state") == "ran":
        reuse = payload.get("reuse_summary", {})
        return "\n".join(
            [
                f"state: {payload['state']}",
                f"reason: {payload['reason']}",
                f"job_id: {payload['job_id']}",
                f"run_directory: {payload['run_directory']}",
                f"latest_directory: {payload['latest_directory']}",
                f"image_count: {payload['image_count']}",
                f"new: {reuse.get('new', 0)}",
                f"changed: {reuse.get('changed', 0)}",
                f"unchanged: {reuse.get('unchanged', 0)}",
                f"derived_cache_hit_count: {payload.get('derived_cache_hit_count', 0)}",
                f"derived_cache_miss_count: {payload.get('derived_cache_miss_count', 0)}",
            ]
        )
    return "\n".join(
        [
            f"state: {payload.get('state')}",
            f"reason: {payload.get('reason')}",
            f"image_count: {payload.get('image_count', 0)}",
        ]
    )


def _handle_doctor(args: argparse.Namespace, runtime) -> int:
    local = check_local_caption_backend(_effective_caption_model(args))
    source_checks = _doctor_source_checks(args, runtime.state_root)
    ocr = _doctor_ocr_check(_effective_ocr_mode(args), _effective_ocr_model(args))
    payload = {
        "settings": {
            "path": str(settings_path()),
            "exists": settings_path().exists(),
        },
        "execution": {
            "in_docker_env": os.environ.get("TIMELINE_FOR_IMAGE_IN_DOCKER") == "1",
            "docker_marker_exists": Path("/.dockerenv").exists(),
            "host_cli_allow_env": os.environ.get("TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI") == "1",
            "host_cli_allowed": _host_cli_allowed(),
        },
        "runtime_paths": {
            "appdata_root": str(runtime.appdata_root),
            "outputs_root": str(runtime.outputs_root),
            "state_root": str(runtime.state_root),
            "outputs": _doctor_path_check(runtime.outputs_root, needs_write=True),
            "state": _doctor_path_check(runtime.state_root, needs_write=True),
        },
        "sources": source_checks,
        "huggingface_local_backend": local,
        "ocr_backend": ocr,
    }
    lines = [
        "settings:",
        f"  path: {payload['settings']['path']}",
        f"  exists: {payload['settings']['exists']}",
        "execution:",
        f"  in_docker_env: {payload['execution']['in_docker_env']}",
        f"  host_cli_allowed: {payload['execution']['host_cli_allowed']}",
        "runtime_paths:",
        f"  outputs_root: {payload['runtime_paths']['outputs_root']}",
        f"  outputs_writable: {payload['runtime_paths']['outputs']['writable']}",
        f"  state_root: {payload['runtime_paths']['state_root']}",
        f"  state_writable: {payload['runtime_paths']['state']['writable']}",
        "sources:",
        *[
            f"  - path: {source['path']} exists={source['exists']} readable={source['readable']} recursive={source['recursive']}"
            for source in source_checks
        ],
        "huggingface_local_backend:",
        f"  backend: {local['backend']}",
        f"  model: {local['model']}",
        f"  dependencies_available: {local['dependencies_available']}",
        f"  model_loadable: {local['model_loadable']}",
        "ocr_backend:",
        f"  backend: {ocr['backend']}",
        f"  model: {ocr['model']}",
        f"  dependencies_available: {ocr['dependencies_available']}",
        f"  languages_available: {ocr['languages_available']}",
    ]
    if local["warning"]:
        lines.append(f"  warning: {local['warning']}")
    if ocr["warning"]:
        lines.append(f"  warning: {ocr['warning']}")
    _print_output(args.format, payload, "\n".join(lines))
    return 0


def _doctor_source_checks(args: argparse.Namespace, state_root: Path) -> list[dict[str, Any]]:
    try:
        source_specs = _resolve_source_specs(args, state_root)
    except (FileNotFoundError, ValueError) as exc:
        return [{"path": None, "exists": False, "readable": False, "recursive": None, "warning": str(exc)}]
    checks = []
    for path, recursive in source_specs:
        check = _doctor_path_check(path, needs_write=False)
        check["recursive"] = recursive
        checks.append(check)
    return checks


def _doctor_path_check(path: Path, needs_write: bool) -> dict[str, Any]:
    nearest_parent = _nearest_existing_parent(path)
    exists = path.exists()
    readable = os.access(path, os.R_OK) if exists else False
    writable = os.access(path, os.W_OK) if exists else os.access(nearest_parent, os.W_OK)
    return {
        "path": str(path),
        "exists": exists,
        "is_file": path.is_file() if exists else False,
        "is_dir": path.is_dir() if exists else False,
        "readable": readable,
        "writable": writable if needs_write else None,
        "nearest_existing_parent": str(nearest_parent),
        "parent_writable": os.access(nearest_parent, os.W_OK),
    }


def _nearest_existing_parent(path: Path) -> Path:
    current = path if path.exists() else path.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _doctor_ocr_check(mode: str, model: str | None) -> dict[str, Any]:
    resolved_model = resolve_ocr_model(mode, model)
    payload: dict[str, Any] = {
        "backend": "tesseract",
        "mode": mode,
        "model": resolved_model,
        "dependencies_available": False,
        "languages": [],
        "required_languages": _required_ocr_languages(resolved_model),
        "languages_available": False,
        "warning": None,
    }
    if mode in {"off", "mock"}:
        payload["dependencies_available"] = True
        payload["languages_available"] = True
        return payload
    try:
        import pytesseract

        languages = sorted(pytesseract.get_languages(config=""))
        payload["dependencies_available"] = True
        payload["languages"] = languages
        required = payload["required_languages"]
        payload["languages_available"] = all(language in languages for language in required)
        if not payload["languages_available"]:
            payload["warning"] = f"Missing OCR languages: {', '.join(language for language in required if language not in languages)}"
    except Exception as exc:
        payload["warning"] = f"Tesseract OCR backend is not ready: {exc}"
    return payload


def _required_ocr_languages(model: str | None) -> list[str]:
    if not model:
        return []
    if model.startswith("tesseract:"):
        value = model.split(":", 1)[1]
    else:
        value = model
    return [part for part in value.split("+") if part]


def _prepare_job(args: argparse.Namespace, outputs_root: Path, state_root: Path, run_reason: str = "manual") -> tuple[JobRequest, Path]:
    source_specs = _resolve_source_specs(args, state_root)
    items = discover_image_sources(source_specs, mock=_effective_mock(args))
    if not items:
        raise ValueError("No supported image files found.")
    processing_profile = build_processing_profile(
        _effective_caption_mode(args),
        _effective_caption_model(args),
        _effective_ocr_mode(args),
        _effective_ocr_model(args),
    )
    reuse_summary = compare_items(state_root, items, processing_profile)
    return _create_job_request(args, outputs_root, source_specs, items, processing_profile, reuse_summary, run_reason)


def _create_job_request(
    args: argparse.Namespace,
    outputs_root: Path,
    source_specs: list[SourceSpec],
    items: list,
    processing_profile: str,
    reuse_summary: dict[str, int],
    run_reason: str,
) -> tuple[JobRequest, Path]:
    job_id = create_job_id(outputs_root)
    source_paths = [path for path, _ in source_specs]
    recursive = _source_specs_recursive_summary(source_specs)
    request = JobRequest(
        job_id=job_id,
        created_at=now_iso(),
        source_paths=[str(path.resolve()) for path in source_paths],
        source_options=_source_options(source_specs),
        recursive=recursive,
        mock=_effective_mock(args),
        caption_mode=_effective_caption_mode(args),
        caption_model=_effective_caption_model(args),
        ocr_mode=_effective_ocr_mode(args),
        ocr_model=_effective_ocr_model(args),
        annotations_file=_effective_annotations_file(args),
        processing_profile=processing_profile,
        reuse_summary=reuse_summary,
        items=items,
        run_reason=run_reason,
    )
    job_dir = outputs_root / job_id
    create_job(job_dir, request)
    return request, job_dir


def _handle_settings(args: argparse.Namespace) -> int:
    if args.settings_command == "init":
        created, path = init_settings()
        payload = {"created": created, "settings_path": str(path)}
        text = f"created: {path}" if created else f"exists: {path}"
        _print_output(args.format, payload, text)
        return 0
    raise ValueError("Unsupported settings command.")


def _handle_sources(args: argparse.Namespace, state_root: Path) -> int:
    if args.sources_command == "list":
        sources = load_sources(state_root)
        text = "\n".join(
            f"- {source.get('path')} recursive={source.get('recursive', True)}"
            for source in sources
        ) or "No sources configured."
        _print_output(args.format, {"sources": sources}, text)
        return 0
    if args.sources_command == "add":
        source = add_source(state_root, path_from_user_value(args.path), recursive=not args.no_recursive)
        _print_output(
            args.format,
            {"source": source},
            f"added: {source['path']} recursive={source.get('recursive', True)}",
        )
        return 0
    if args.sources_command == "remove":
        source_path = path_from_user_value(args.path)
        removed = remove_source(state_root, source_path)
        _print_output(
            args.format,
            {"removed": removed, "path": str(source_path)},
            "removed" if removed else "source not found",
        )
        return 0
    raise ValueError("Unsupported sources command.")


def _handle_list_jobs(args: argparse.Namespace, outputs_root: Path) -> int:
    rows = []
    for job_dir in reversed(iter_run_dirs(outputs_root)):
        request = load_request(job_dir)
        status = load_status(job_dir)
        result = read_json(result_path(job_dir)) if result_path(job_dir).exists() else {}
        rows.append(
            {
                "job_id": request["job_id"],
                "state": status["state"],
                "current_stage": status["current_stage"],
                "created_at": request["created_at"],
                "updated_at": status["updated_at"],
                "image_count": len(request["items"]),
                "archive_path": result.get("archive_path"),
            }
        )
    text = "\n".join(f"{row['job_id']} {row['state']} images={row['image_count']}" for row in rows) or "No jobs found."
    _print_output(args.format, rows, text)
    return 0


def _handle_show_job(args: argparse.Namespace, outputs_root: Path) -> int:
    job_dir = outputs_root / args.job
    if not job_dir.exists():
        raise FileNotFoundError(f"Job not found: {args.job}")
    payload = {
        "request": load_request(job_dir),
        "status": load_status(job_dir),
        "result": read_json(result_path(job_dir)) if result_path(job_dir).exists() else None,
    }
    text = "\n".join(
        [
            f"job_id: {payload['request']['job_id']}",
            f"state: {payload['status']['state']}",
            f"image_count: {len(payload['request']['items'])}",
            f"archive_path: {(payload['result'] or {}).get('archive_path') or ''}",
        ]
    )
    _print_output(args.format, payload, text)
    return 0


def _resolve_source_specs(args: argparse.Namespace, state_root: Path) -> list[SourceSpec]:
    directories = getattr(args, "directory", []) or []
    files = getattr(args, "file", []) or []
    no_recursive = bool(getattr(args, "no_recursive", False))
    if directories or files:
        recursive = not no_recursive
        return [(path_from_user_value(value), recursive) for value in [*directories, *files]]

    configured = config_sources(_config(args))
    if configured:
        return [(path_from_user_value(source["path"]), bool(source.get("recursive", True)) and not no_recursive) for source in configured]

    registered = load_sources(state_root)
    if registered:
        return [(Path(source["path"]), bool(source.get("recursive", True)) and not no_recursive) for source in registered if source.get("path")]

    raise ValueError("Pass at least one --directory or --file, set config sources, or configure sources with `sources add`.")


def _resolve_sources(args: argparse.Namespace, state_root: Path) -> list[Path]:
    source_paths = [path for path, _ in _resolve_source_specs(args, state_root)]
    if not source_paths:
        raise ValueError("Pass at least one --directory or --file, set config sources, or configure sources with `sources add`.")
    return source_paths


def _resolve_recursive(args: argparse.Namespace, state_root: Path) -> bool:
    return _source_specs_recursive_summary(_resolve_source_specs(args, state_root))


def _source_specs_recursive_summary(source_specs: list[SourceSpec]) -> bool:
    return all(recursive for _, recursive in source_specs)


def _source_options(source_specs: list[SourceSpec]) -> list[dict[str, Any]]:
    return [{"path": str(path.resolve()), "recursive": recursive} for path, recursive in source_specs]


def _config(args: argparse.Namespace) -> dict[str, Any]:
    return getattr(args, "config_payload", {}) or {}


def _effective_mock(args: argparse.Namespace) -> bool:
    if getattr(args, "mock", None) is not None:
        return bool(args.mock)
    value = _config(args).get("mock")
    return bool(value) if value is not None else False


def _effective_caption_mode(args: argparse.Namespace) -> str:
    if getattr(args, "caption_mode", None):
        return args.caption_mode
    return nested_value(_config(args), "caption", "mode", "caption_mode") or "local"


def _effective_caption_model(args: argparse.Namespace) -> str | None:
    if getattr(args, "caption_model", None):
        return args.caption_model
    return nested_value(_config(args), "caption", "model", "caption_model")


def _effective_ocr_mode(args: argparse.Namespace) -> str:
    if getattr(args, "ocr_mode", None):
        return args.ocr_mode
    return nested_value(_config(args), "ocr", "mode", "ocr_mode") or "auto"


def _effective_ocr_model(args: argparse.Namespace) -> str | None:
    if getattr(args, "ocr_model", None):
        return args.ocr_model
    return nested_value(_config(args), "ocr", "model", "ocr_model")


def _effective_annotations_file(args: argparse.Namespace) -> str | None:
    if getattr(args, "annotations_file", None):
        return str(path_from_user_value(args.annotations_file))
    value = _config(args).get("annotations_file")
    return str(path_from_user_value(value)) if isinstance(value, str) else None


def _effective_interval_seconds(args: argparse.Namespace) -> float:
    if getattr(args, "interval_seconds", None) is not None:
        return float(args.interval_seconds)
    watch = _config(args).get("watch", {})
    if isinstance(watch, dict) and watch.get("interval_seconds") is not None:
        return float(watch["interval_seconds"])
    return 30.0


def _effective_min_quiet_seconds(args: argparse.Namespace) -> float:
    if getattr(args, "min_quiet_seconds", None) is not None:
        return float(args.min_quiet_seconds)
    watch = _config(args).get("watch", {})
    if isinstance(watch, dict) and watch.get("min_quiet_seconds") is not None:
        return float(watch["min_quiet_seconds"])
    return 2.0


def _print_output(output_format: str, payload: Any, text: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(text)
