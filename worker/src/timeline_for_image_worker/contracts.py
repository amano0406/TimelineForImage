from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ImageItem:
    source_path: str
    relative_path: str
    sha256: str
    size_bytes: int
    format_name: str
    width: int | None
    height: int | None
    captured_at: str | None
    modified_at: str
    timeline_at: str
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    focal_length_mm: float | None = None
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    gps_altitude_m: float | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CaptionRecord:
    source_path: str
    mode: str
    model: str | None
    text: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OcrRecord:
    source_path: str
    mode: str
    model: str | None
    should_run: bool
    check_text: str
    text: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisualObservationRecord:
    source_path: str
    has_people: bool | None
    has_text: bool
    place_hint: str | None
    activities: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    scene_summary: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TimelineGroup:
    group_id: str
    group_type: str
    title: str
    item_count: int
    start_at: str
    end_at: str
    source_paths: list[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HumanAnnotationRecord:
    source_path: str
    tags: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    event: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JobRequest:
    job_id: str
    created_at: str
    source_paths: list[str]
    recursive: bool
    mock: bool
    caption_mode: str
    caption_model: str | None
    ocr_mode: str
    ocr_model: str | None
    annotations_file: str | None
    processing_profile: str
    reuse_summary: dict[str, int]
    items: list[ImageItem]
    source_options: list[dict[str, Any]] = field(default_factory=list)
    run_reason: str = "manual"

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "created_at": self.created_at,
            "source_paths": self.source_paths,
            "source_options": self.source_options,
            "recursive": self.recursive,
            "mock": self.mock,
            "caption_mode": self.caption_mode,
            "caption_model": self.caption_model,
            "ocr_mode": self.ocr_mode,
            "ocr_model": self.ocr_model,
            "annotations_file": self.annotations_file,
            "processing_profile": self.processing_profile,
            "reuse_summary": self.reuse_summary,
            "run_reason": self.run_reason,
            "items": [item.to_dict() for item in self.items],
        }


@dataclass(frozen=True)
class RuntimePaths:
    appdata_root: Path
    outputs_root: Path
    state_root: Path


@dataclass(frozen=True)
class JobStatus:
    state: str
    current_stage: str
    updated_at: str
    items_total: int
    items_done: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
