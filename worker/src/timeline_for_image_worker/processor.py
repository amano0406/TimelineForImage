from __future__ import annotations

import zipfile
from pathlib import Path

from .annotations import load_human_annotations
from .catalog_store import PROCESSING_PROFILE, update_master_catalog
from .captioning import caption_images
from .contracts import ImageItem, JobStatus
from .derived_cache import load_derived_cache, restore_derivatives, save_derived_cache, store_derivatives
from .fs_utils import now_iso, read_json, write_json
from .grouping import build_timeline_groups
from .job_store import manifest_path, request_path, result_path, write_status
from .ocr import run_ocr
from .timeline import render_fidelity_report, render_timeline
from .visual_observations import build_visual_observations


def process_job(job_dir: Path, state_root: Path | None = None) -> None:
    request = read_json(request_path(job_dir))
    items = [ImageItem(**item) for item in request["items"]]
    write_status(
        job_dir,
        JobStatus(
            state="running",
            current_stage="writing artifacts",
            updated_at=now_iso(),
            items_total=len(items),
            items_done=0,
        ),
    )

    processing_profile = request.get("processing_profile", PROCESSING_PROFILE)
    cache, cache_warnings = load_derived_cache(state_root)
    captions_by_path = {}
    ocr_by_path = {}
    visual_observations_by_path = {}
    miss_items: list[ImageItem] = []
    cache_stats = {
        "derived_cache_hit_count": 0,
        "derived_cache_miss_count": 0,
        "reused_caption_count": 0,
        "generated_caption_count": 0,
        "reused_ocr_count": 0,
        "generated_ocr_count": 0,
        "reused_visual_observation_count": 0,
        "generated_visual_observation_count": 0,
        "cache_warning_count": len(cache_warnings),
    }
    for item in items:
        restored = restore_derivatives(cache, item, processing_profile)
        if restored is None:
            cache_stats["derived_cache_miss_count"] += 1
            miss_items.append(item)
            continue
        caption, ocr, observation = restored
        cache_stats["derived_cache_hit_count"] += 1
        if caption is not None:
            captions_by_path[item.source_path] = caption
            cache_stats["reused_caption_count"] += 1
        if ocr is not None:
            ocr_by_path[item.source_path] = ocr
            cache_stats["reused_ocr_count"] += 1
        visual_observations_by_path[item.source_path] = observation
        cache_stats["reused_visual_observation_count"] += 1

    miss_caption_records = caption_images(
        miss_items,
        request.get("caption_mode", "mock"),
        request.get("caption_model"),
    )
    miss_captions_by_path = {caption.source_path: caption for caption in miss_caption_records}
    captions_by_path.update(miss_captions_by_path)
    cache_stats["generated_caption_count"] = len(miss_caption_records)
    miss_ocr_records = run_ocr(
        miss_items,
        request.get("ocr_mode", "auto"),
        request.get("ocr_model"),
    )
    miss_ocr_by_path = {ocr.source_path: ocr for ocr in miss_ocr_records}
    ocr_by_path.update(miss_ocr_by_path)
    cache_stats["generated_ocr_count"] = len(miss_ocr_records)
    miss_visual_observations = build_visual_observations(miss_items, miss_captions_by_path, miss_ocr_by_path)
    for observation in miss_visual_observations:
        visual_observations_by_path[observation.source_path] = observation
    cache_stats["generated_visual_observation_count"] = len(miss_visual_observations)
    for item in miss_items:
        observation = visual_observations_by_path[item.source_path]
        store_derivatives(cache, item, processing_profile, miss_captions_by_path.get(item.source_path), miss_ocr_by_path.get(item.source_path), observation)

    caption_records = [captions_by_path[item.source_path] for item in items if item.source_path in captions_by_path]
    ocr_records = [ocr_by_path[item.source_path] for item in items if item.source_path in ocr_by_path]
    visual_observations = [visual_observations_by_path[item.source_path] for item in items if item.source_path in visual_observations_by_path]
    annotations = load_human_annotations(items, request.get("annotations_file"))
    annotations_by_path = {annotation.source_path: annotation for annotation in annotations}
    timeline_groups = build_timeline_groups(items, annotations)
    catalog = {
        "items": [item.to_dict() for item in items],
        "captions": [caption.to_dict() for caption in caption_records],
        "ocr": [ocr.to_dict() for ocr in ocr_records],
        "visual_observations": [record.to_dict() for record in visual_observations],
        "timeline_groups": [group.to_dict() for group in timeline_groups],
        "human_annotations": [annotation.to_dict() for annotation in annotations],
    }
    manifest = {
        "product": "TimelineForImage",
        "job_id": request["job_id"],
        "created_at": request["created_at"],
        "run_reason": request.get("run_reason", "manual"),
        "source_paths": request["source_paths"],
        "source_options": request.get("source_options", []),
        "recursive": request["recursive"],
        "mock": request["mock"],
        "caption_mode": request.get("caption_mode", "mock"),
        "caption_model": request.get("caption_model"),
        "ocr_mode": request.get("ocr_mode", "auto"),
        "ocr_model": request.get("ocr_model"),
        "annotations_file": request.get("annotations_file"),
        "processing_profile": processing_profile,
        "reuse_summary": request.get("reuse_summary", {}),
        "derived_cache": cache_stats,
        "cache_warnings": cache_warnings,
        "image_count": len(items),
        "artifact_files": [
            "README.md",
            "timeline.md",
            "catalog.json",
            "captions.json",
            "ocr.json",
            "visual_observations.json",
            "timeline_groups.json",
            "annotations.json",
            "manifest.json",
            "fidelity_report.md",
        ],
    }

    write_json(job_dir / "catalog.json", catalog)
    write_json(job_dir / "captions.json", {"captions": [caption.to_dict() for caption in caption_records]})
    write_json(job_dir / "ocr.json", {"ocr": [ocr.to_dict() for ocr in ocr_records]})
    write_json(job_dir / "visual_observations.json", {"visual_observations": [record.to_dict() for record in visual_observations]})
    write_json(job_dir / "timeline_groups.json", {"timeline_groups": [group.to_dict() for group in timeline_groups]})
    write_json(job_dir / "annotations.json", {"annotations": [annotation.to_dict() for annotation in annotations]})
    write_json(manifest_path(job_dir), manifest)
    (job_dir / "timeline.md").write_text(
        render_timeline(items, captions_by_path, ocr_by_path, visual_observations_by_path, annotations_by_path, timeline_groups),
        encoding="utf-8",
    )
    (job_dir / "fidelity_report.md").write_text(
        render_fidelity_report(items, request.get("reuse_summary", {}), caption_records, ocr_records, visual_observations, timeline_groups, annotations, cache_stats, cache_warnings),
        encoding="utf-8",
    )
    readme = _render_export_readme(len(items), request.get("caption_mode", "mock"), request.get("ocr_mode", "auto"))
    (job_dir / "README.md").write_text(readme, encoding="utf-8")

    export_dir = job_dir / "export"
    export_dir.mkdir(exist_ok=True)
    archive_path = export_dir / "TimelineForImage-export.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in manifest["artifact_files"]:
            archive.write(job_dir / name, name)

    result = {
        "job_id": request["job_id"],
        "state": "completed",
        "run_reason": request.get("run_reason", "manual"),
        "image_count": len(items),
        "caption_count": len(caption_records),
        "ocr_count": len(ocr_records),
        "ocr_ran_count": sum(1 for record in ocr_records if record.should_run),
        "visual_observation_count": len(visual_observations),
        "timeline_group_count": len(timeline_groups),
        "annotation_count": len(annotations),
        **cache_stats,
        "cache_warnings": cache_warnings,
        "reuse_summary": request.get("reuse_summary", {}),
        "archive_path": str(archive_path),
    }
    write_json(result_path(job_dir), result)
    save_derived_cache(state_root, cache)
    if state_root is not None:
        update_master_catalog(state_root, items, processing_profile)
    write_status(
        job_dir,
        JobStatus(
            state="completed",
            current_stage="completed",
            updated_at=now_iso(),
            items_total=len(items),
            items_done=len(items),
        ),
    )


def _render_export_readme(image_count: int, caption_mode: str, ocr_mode: str) -> str:
    return "\n".join(
        [
            "# TimelineForImage Export",
            "",
            f"Image count: {image_count}",
            f"Caption mode: {caption_mode}",
            f"OCR mode: {ocr_mode}",
            "",
            "This package contains metadata-derived timeline artifacts.",
            "Original image files are not included.",
            "",
        ]
    )
