from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .contracts import JobRequest, JobStatus
from .fs_utils import read_json, write_json


def create_job_id(outputs_root: Path) -> str:
    base = datetime.now(timezone.utc).strftime("job-%Y%m%d-%H%M%S")
    candidate = base
    suffix = 1
    while (outputs_root / candidate).exists():
        suffix += 1
        candidate = f"{base}-{suffix:02d}"
    return candidate


def create_job(job_dir: Path, request: JobRequest) -> None:
    job_dir.mkdir(parents=True, exist_ok=False)
    write_json(request_path(job_dir), request.to_dict())
    write_status(
        job_dir,
        JobStatus(
            state="queued",
            current_stage="created",
            updated_at=request.created_at,
            items_total=len(request.items),
            items_done=0,
        ),
    )


def iter_run_dirs(outputs_root: Path) -> list[Path]:
    if not outputs_root.exists():
        return []
    return sorted(path for path in outputs_root.iterdir() if path.is_dir() and path.name.startswith("job-"))


def request_path(job_dir: Path) -> Path:
    return job_dir / "request.json"


def status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def result_path(job_dir: Path) -> Path:
    return job_dir / "result.json"


def manifest_path(job_dir: Path) -> Path:
    return job_dir / "manifest.json"


def load_request(job_dir: Path) -> dict:
    return read_json(request_path(job_dir))


def load_status(job_dir: Path) -> dict:
    return read_json(status_path(job_dir))


def write_status(job_dir: Path, status: JobStatus) -> None:
    write_json(status_path(job_dir), status.to_dict())
