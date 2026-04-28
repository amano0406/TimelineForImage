from __future__ import annotations

from pathlib import Path
from typing import Any

from .fs_utils import read_json, write_json


def sources_path(state_root: Path) -> Path:
    return state_root / "sources.json"


def load_sources(state_root: Path) -> list[dict[str, Any]]:
    path = sources_path(state_root)
    if not path.exists():
        return []
    payload = read_json(path)
    sources = payload.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources.json is invalid: sources must be a list.")
    return sources


def save_sources(state_root: Path, sources: list[dict[str, Any]]) -> None:
    write_json(sources_path(state_root), {"sources": sources})


def add_source(state_root: Path, source_path: Path, recursive: bool = True) -> dict[str, Any]:
    resolved = str(source_path.expanduser().resolve())
    sources = load_sources(state_root)
    for source in sources:
        if source.get("path") == resolved:
            source["recursive"] = recursive
            save_sources(state_root, sources)
            return source
    source = {"path": resolved, "recursive": recursive}
    sources.append(source)
    save_sources(state_root, sources)
    return source


def remove_source(state_root: Path, source_path: Path) -> bool:
    resolved = str(source_path.expanduser().resolve())
    sources = load_sources(state_root)
    kept = [source for source in sources if source.get("path") != resolved]
    if len(kept) == len(sources):
        return False
    save_sources(state_root, kept)
    return True


def configured_source_paths(state_root: Path) -> list[Path]:
    return [Path(source["path"]) for source in load_sources(state_root) if source.get("path")]
