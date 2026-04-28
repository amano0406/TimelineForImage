from __future__ import annotations

from .contracts import CaptionRecord, HumanAnnotationRecord, ImageItem, OcrRecord, TimelineGroup, VisualObservationRecord


def render_timeline(
    items: list[ImageItem],
    captions_by_path: dict[str, CaptionRecord] | None = None,
    ocr_by_path: dict[str, OcrRecord] | None = None,
    observations_by_path: dict[str, VisualObservationRecord] | None = None,
    annotations_by_path: dict[str, HumanAnnotationRecord] | None = None,
    timeline_groups: list[TimelineGroup] | None = None,
) -> str:
    captions = captions_by_path or {}
    ocr_records = ocr_by_path or {}
    observations = observations_by_path or {}
    annotations = annotations_by_path or {}
    groups = timeline_groups or []
    lines = [
        "# Image Timeline",
        "",
        f"Image count: {len(items)}",
        "",
    ]
    if groups:
        lines.extend(["## Groups", ""])
        for group in groups:
            lines.extend(
                [
                    f"### {group.title}",
                    "",
                    f"- Group ID: `{group.group_id}`",
                    f"- Type: {group.group_type}",
                    f"- Items: {group.item_count}",
                    f"- Range: {group.start_at} to {group.end_at}",
                    f"- Reasoning: {group.reasoning}",
                    "",
                ]
            )
    for item in items:
        dimensions = f"{item.width}x{item.height}" if item.width and item.height else "unknown dimensions"
        lines.extend(
            [
                f"## {item.timeline_at} - {item.relative_path}",
                "",
                f"- Source: `{item.source_path}`",
                f"- Format: {item.format_name}",
                f"- Dimensions: {dimensions}",
                f"- Size: {item.size_bytes} bytes",
                f"- SHA-256: `{item.sha256}`",
                f"- Captured at: {item.captured_at or 'unknown'}",
                f"- Modified at: {item.modified_at}",
                f"- Camera: {_format_camera(item)}",
                f"- Lens: {item.lens_model or 'unknown'}",
                f"- Focal length: {_format_mm(item.focal_length_mm)}",
                f"- GPS: {_format_gps(item)}",
            ]
        )
        if item.warnings:
            lines.append(f"- Warnings: {'; '.join(item.warnings)}")
        caption = captions.get(item.source_path)
        if caption is not None:
            lines.extend(
                [
                    f"- Caption mode: {caption.mode}",
                    f"- Caption model: {caption.model or 'none'}",
                    f"- Caption: {caption.text or 'unavailable'}",
                ]
            )
            if caption.warnings:
                lines.append(f"- Caption warnings: {'; '.join(caption.warnings)}")
        ocr = ocr_records.get(item.source_path)
        if ocr is not None:
            lines.extend(
                [
                    f"- OCR mode: {ocr.mode}",
                    f"- OCR model: {ocr.model or 'none'}",
                    f"- OCR should run: {ocr.should_run}",
                    f"- OCR check: {ocr.check_text or 'unavailable'}",
                    f"- OCR text: {ocr.text or 'unavailable'}",
                ]
            )
            if ocr.warnings:
                lines.append(f"- OCR warnings: {'; '.join(ocr.warnings)}")
        observation = observations.get(item.source_path)
        if observation is not None:
            lines.extend(
                [
                    f"- Has people: {_format_optional_bool(observation.has_people)}",
                    f"- Has text: {observation.has_text}",
                    f"- Place hint: {observation.place_hint or 'unknown'}",
                    f"- Objects: {', '.join(observation.objects) or 'none'}",
                    f"- Activities: {', '.join(observation.activities) or 'none'}",
                ]
            )
            if observation.warnings:
                lines.append(f"- Observation warnings: {'; '.join(observation.warnings)}")
        annotation = annotations.get(item.source_path)
        if annotation is not None:
            lines.extend(
                [
                    f"- Human tags: {', '.join(annotation.tags) or 'none'}",
                    f"- Human people: {', '.join(annotation.people) or 'none'}",
                    f"- Human event: {annotation.event or 'none'}",
                    f"- Human note: {annotation.note or 'none'}",
                ]
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_fidelity_report(
    items: list[ImageItem],
    reuse_summary: dict[str, int] | None = None,
    captions: list[CaptionRecord] | None = None,
    ocr: list[OcrRecord] | None = None,
    observations: list[VisualObservationRecord] | None = None,
    timeline_groups: list[TimelineGroup] | None = None,
    annotations: list[HumanAnnotationRecord] | None = None,
    cache_stats: dict[str, int] | None = None,
    cache_warnings: list[str] | None = None,
) -> str:
    warning_count = sum(len(item.warnings) for item in items)
    missing_capture = sum(1 for item in items if item.captured_at is None)
    missing_dimensions = sum(1 for item in items if item.width is None or item.height is None)
    camera_count = sum(1 for item in items if item.camera_make or item.camera_model)
    lens_count = sum(1 for item in items if item.lens_model)
    gps_count = sum(1 for item in items if item.gps_latitude is not None and item.gps_longitude is not None)
    reuse = reuse_summary or {}
    caption_records = captions or []
    caption_warnings = sum(len(caption.warnings) for caption in caption_records)
    ocr_records = ocr or []
    ocr_warnings = sum(len(record.warnings) for record in ocr_records)
    ocr_ran = sum(1 for record in ocr_records if record.should_run)
    observation_records = observations or []
    observation_warnings = sum(len(record.warnings) for record in observation_records)
    group_records = timeline_groups or []
    annotation_records = annotations or []
    cache = cache_stats or {}
    warnings = cache_warnings or []
    lines = [
        "# Fidelity Report",
        "",
        f"- Image count: {len(items)}",
        f"- New images: {reuse.get('new', 0)}",
        f"- Changed images: {reuse.get('changed', 0)}",
        f"- Unchanged images: {reuse.get('unchanged', 0)}",
        f"- Warning count: {warning_count}",
        f"- Missing capture timestamps: {missing_capture}",
        f"- Missing dimensions: {missing_dimensions}",
        f"- Images with camera metadata: {camera_count}",
        f"- Images with lens metadata: {lens_count}",
        f"- Images with GPS metadata: {gps_count}",
        f"- Caption count: {len(caption_records)}",
        f"- Caption warning count: {caption_warnings}",
        f"- OCR record count: {len(ocr_records)}",
        f"- OCR ran count: {ocr_ran}",
        f"- OCR warning count: {ocr_warnings}",
        f"- Visual observation count: {len(observation_records)}",
        f"- Visual observation warning count: {observation_warnings}",
        f"- Timeline group count: {len(group_records)}",
        f"- Human annotation count: {len(annotation_records)}",
        f"- Derived cache hits: {cache.get('derived_cache_hit_count', 0)}",
        f"- Derived cache misses: {cache.get('derived_cache_miss_count', 0)}",
        f"- Reused captions: {cache.get('reused_caption_count', 0)}",
        f"- Generated captions: {cache.get('generated_caption_count', 0)}",
        f"- Reused OCR records: {cache.get('reused_ocr_count', 0)}",
        f"- Generated OCR records: {cache.get('generated_ocr_count', 0)}",
        f"- Reused visual observations: {cache.get('reused_visual_observation_count', 0)}",
        f"- Generated visual observations: {cache.get('generated_visual_observation_count', 0)}",
        f"- Derived cache warning count: {len(warnings)}",
        "",
        "## Limits",
        "",
        "- Original images are not included in the export ZIP.",
        "- EXIF timestamps without timezone are normalized as UTC.",
        "- AI captions are derived evidence, not observed facts.",
        "- Visual observations are derived from captions/OCR and are not independent object detection.",
        "- OCR should-run decisions are derived evidence and can be wrong.",
        "- Timeline grouping is heuristic.",
        "- Person identity recognition is not performed.",
    ]
    if warnings:
        lines.extend(["", "## Cache Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"


def _format_optional_bool(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return str(value)


def _format_camera(item: ImageItem) -> str:
    parts = [part for part in [item.camera_make, item.camera_model] if part]
    return " ".join(parts) if parts else "unknown"


def _format_mm(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:g} mm"


def _format_gps(item: ImageItem) -> str:
    if item.gps_latitude is None or item.gps_longitude is None:
        return "unknown"
    parts = [f"{item.gps_latitude:.8f}", f"{item.gps_longitude:.8f}"]
    if item.gps_altitude_m is not None:
        parts.append(f"{item.gps_altitude_m:g} m")
    return ", ".join(parts)
