from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import math
import re

from .contracts import HumanAnnotationRecord, ImageItem, TimelineGroup

SEQUENCE_GAP = timedelta(minutes=10)
LOCATION_RADIUS_METERS = 250.0


def build_timeline_groups(items: list[ImageItem], annotations: list[HumanAnnotationRecord] | None = None) -> list[TimelineGroup]:
    by_day: dict[str, list[ImageItem]] = defaultdict(list)
    for item in items:
        by_day[_day_key(item.timeline_at)].append(item)

    groups: list[TimelineGroup] = []
    for day in sorted(by_day):
        day_items = sorted(by_day[day], key=lambda item: item.timeline_at)
        groups.append(
            TimelineGroup(
                group_id=f"day:{day}",
                group_type="day",
                title=day,
                item_count=len(day_items),
                start_at=day_items[0].timeline_at,
                end_at=day_items[-1].timeline_at,
                source_paths=[item.source_path for item in day_items],
                reasoning="Grouped by timeline date.",
            )
        )
        groups.extend(_build_sequence_groups(day, day_items))
    groups.extend(_build_event_groups(items, annotations or []))
    groups.extend(_build_location_groups(items))
    return groups


def _day_key(value: str) -> str:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return value[:10] if len(value) >= 10 else "unknown-date"


def _build_sequence_groups(day: str, items: list[ImageItem]) -> list[TimelineGroup]:
    groups: list[TimelineGroup] = []
    current: list[ImageItem] = []
    previous_at: datetime | None = None
    sequence_index = 1
    for item in items:
        item_at = _parse_datetime(item.timeline_at)
        if item_at is None:
            _append_sequence_group(groups, day, sequence_index, current)
            if len(current) >= 2:
                sequence_index += 1
            current = []
            previous_at = None
            continue
        if previous_at is not None and item_at - previous_at > SEQUENCE_GAP:
            _append_sequence_group(groups, day, sequence_index, current)
            if len(current) >= 2:
                sequence_index += 1
            current = []
        current.append(item)
        previous_at = item_at
    _append_sequence_group(groups, day, sequence_index, current)
    return groups


def _append_sequence_group(groups: list[TimelineGroup], day: str, sequence_index: int, items: list[ImageItem]) -> None:
    if len(items) < 2:
        return
    groups.append(
        TimelineGroup(
            group_id=f"sequence:{day}:{sequence_index}",
            group_type="sequence",
            title=f"{day} sequence {sequence_index}",
            item_count=len(items),
            start_at=items[0].timeline_at,
            end_at=items[-1].timeline_at,
            source_paths=[item.source_path for item in items],
            reasoning=f"Grouped as a sequence because adjacent timeline timestamps are within {int(SEQUENCE_GAP.total_seconds() // 60)} minutes.",
        )
    )


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _build_event_groups(items: list[ImageItem], annotations: list[HumanAnnotationRecord]) -> list[TimelineGroup]:
    items_by_path = {item.source_path: item for item in items}
    by_event: dict[str, list[ImageItem]] = defaultdict(list)
    for annotation in annotations:
        if not annotation.event:
            continue
        item = items_by_path.get(annotation.source_path)
        if item is not None:
            by_event[annotation.event].append(item)

    groups: list[TimelineGroup] = []
    for event in sorted(by_event):
        event_items = sorted(by_event[event], key=lambda item: (item.timeline_at, item.relative_path.lower()))
        groups.append(
            TimelineGroup(
                group_id=f"event:{_slug(event)}",
                group_type="event",
                title=event,
                item_count=len(event_items),
                start_at=event_items[0].timeline_at,
                end_at=event_items[-1].timeline_at,
                source_paths=[item.source_path for item in event_items],
                reasoning="Grouped by matching human annotation event.",
            )
        )
    return groups


def _build_location_groups(items: list[ImageItem]) -> list[TimelineGroup]:
    clusters: list[dict[str, object]] = []
    gps_items = [item for item in items if item.gps_latitude is not None and item.gps_longitude is not None]
    for item in sorted(gps_items, key=lambda value: (value.timeline_at, value.relative_path.lower())):
        assigned = False
        for cluster in clusters:
            if _distance_meters(float(cluster["latitude"]), float(cluster["longitude"]), item.gps_latitude or 0.0, item.gps_longitude or 0.0) <= LOCATION_RADIUS_METERS:
                cluster_items = cluster["items"]
                assert isinstance(cluster_items, list)
                cluster_items.append(item)
                cluster["latitude"] = sum(member.gps_latitude or 0.0 for member in cluster_items) / len(cluster_items)
                cluster["longitude"] = sum(member.gps_longitude or 0.0 for member in cluster_items) / len(cluster_items)
                assigned = True
                break
        if not assigned:
            clusters.append({"latitude": item.gps_latitude, "longitude": item.gps_longitude, "items": [item]})

    groups: list[TimelineGroup] = []
    location_index = 1
    for cluster in clusters:
        cluster_items = cluster["items"]
        assert isinstance(cluster_items, list)
        if len(cluster_items) < 2:
            continue
        groups.append(
            TimelineGroup(
                group_id=f"location:{location_index}",
                group_type="location",
                title=f"GPS location {location_index}",
                item_count=len(cluster_items),
                start_at=cluster_items[0].timeline_at,
                end_at=cluster_items[-1].timeline_at,
                source_paths=[item.source_path for item in cluster_items],
                reasoning=f"Grouped by GPS coordinates within {int(LOCATION_RADIUS_METERS)} meters.",
            )
        )
        location_index += 1
    return groups


def _distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_meters = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius_meters * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"
