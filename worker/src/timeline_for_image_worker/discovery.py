from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .contracts import ImageItem
from .image_metadata import SUPPORTED_EXTENSIONS, read_image_item

SourceSpec = tuple[Path, bool]


def discover_images(source_paths: list[Path], recursive: bool, mock: bool = False) -> list[ImageItem]:
    return discover_image_sources([(path, recursive) for path in source_paths], mock=mock)


def discover_image_sources(source_specs: Sequence[SourceSpec], mock: bool = False) -> list[ImageItem]:
    roots = [path.resolve() for path, _ in source_specs]
    files: list[Path] = []
    for source, recursive in [(path.resolve(), recursive) for path, recursive in source_specs]:
        if source.is_file():
            files.append(source)
            continue
        if not source.exists():
            raise FileNotFoundError(f"Source path does not exist: {source}")
        if not source.is_dir():
            raise ValueError(f"Source path is not a file or directory: {source}")
        iterator = source.rglob("*") if recursive else source.glob("*")
        files.extend(path for path in iterator if path.is_file())

    image_files = sorted(
        {path.resolve() for path in files if path.suffix.lower() in SUPPORTED_EXTENSIONS},
        key=lambda path: str(path).lower(),
    )
    return sorted(
        [read_image_item(path, roots, mock=mock) for path in image_files],
        key=lambda item: (item.timeline_at, item.relative_path.lower()),
    )
