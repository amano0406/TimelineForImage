from __future__ import annotations

import os
import shutil
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .fs_utils import now_iso, write_json


class LockTimeoutError(TimeoutError):
    pass


@contextmanager
def exclusive_lock(
    state_root: Path,
    name: str,
    timeout_seconds: float | None = None,
    stale_seconds: float | None = None,
    poll_interval_seconds: float = 0.1,
) -> Iterator[Path]:
    timeout = env_float("TIMELINE_FOR_IMAGE_OPERATION_LOCK_TIMEOUT_SECONDS", 30.0, timeout_seconds)
    stale_after = env_float("TIMELINE_FOR_IMAGE_OPERATION_LOCK_STALE_SECONDS", 3600.0, stale_seconds)
    lock_dir = state_root / "locks" / f"{name}.lock"
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    acquired = False
    while True:
        try:
            lock_dir.mkdir()
            acquired = True
            write_json(
                lock_dir / "owner.json",
                {
                    "created_at": now_iso(),
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "name": name,
                },
            )
            break
        except FileExistsError:
            remove_stale_lock(lock_dir, stale_after)
            if time.monotonic() >= deadline:
                raise LockTimeoutError(f"Timed out waiting for operation lock: {lock_dir}")
            time.sleep(poll_interval_seconds)
    try:
        yield lock_dir
    finally:
        if acquired:
            shutil.rmtree(lock_dir, ignore_errors=True)


def remove_stale_lock(lock_dir: Path, stale_seconds: float) -> None:
    try:
        age = time.time() - lock_dir.stat().st_mtime
    except FileNotFoundError:
        return
    if age > stale_seconds:
        shutil.rmtree(lock_dir, ignore_errors=True)


def env_float(name: str, default: float, override: float | None) -> float:
    if override is not None:
        return float(override)
    raw = os.environ.get(name)
    return float(raw) if raw else default
