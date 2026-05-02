from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ImageSource:
    item_id: str
    source_path: str
    relative_path: str
    display_name: str
    sha256: str
    size_bytes: int
    modified_at: str
    format_name: str
    width: int | None
    height: int | None
    captured_at: str | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunStatus:
    schema_version: int = 1
    run_id: str = ""
    state: str = "pending"
    current_stage: str = "queued"
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    items_total: int = 0
    items_done: int = 0
    items_skipped: int = 0
    items_failed: int = 0
    current_item: str | None = None
    progress_percent: float = 0.0
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
