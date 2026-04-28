from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .fs_utils import read_json, write_json
from .job_store import manifest_path, request_path, result_path, status_path


def sync_latest_output(job_dir: Path, outputs_root: Path) -> dict[str, str]:
    latest_dir = outputs_root / "latest"
    if latest_dir.exists() and not latest_dir.is_dir():
        raise ValueError(f"Latest output path exists and is not a directory: {latest_dir}")
    latest_dir.mkdir(parents=True, exist_ok=True)

    result = read_json(result_path(job_dir))
    latest_archive_path = latest_dir / "TimelineForImage-export.zip"
    result["latest_directory"] = str(latest_dir)
    result["latest_archive_path"] = str(latest_archive_path)
    write_json(result_path(job_dir), result)

    manifest = read_json(manifest_path(job_dir))
    artifact_files = manifest.get("artifact_files", [])
    if not isinstance(artifact_files, list):
        artifact_files = []
    for path in [request_path(job_dir), status_path(job_dir), result_path(job_dir), manifest_path(job_dir)]:
        _copy_if_exists(path, latest_dir / path.name)
    for name in artifact_files:
        if isinstance(name, str):
            _copy_if_exists(job_dir / name, latest_dir / name)

    archive_path = Path(str(result.get("archive_path", "")))
    if archive_path.exists():
        shutil.copy2(archive_path, latest_archive_path)
    return {"latest_directory": str(latest_dir), "latest_archive_path": str(latest_archive_path)}


def latest_payload(job_dir: Path, outputs_root: Path) -> dict[str, Any]:
    latest = sync_latest_output(job_dir, outputs_root)
    return {"job_id": job_dir.name, **latest}


def _copy_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
