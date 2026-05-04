# Pipeline

[Back to README](../README.md)

TimelineForImage is a local single-image processing pipeline. It produces stable records for downstream systems; it does not attempt cross-image semantic grouping.

## Stages

1. Load `settings.json`.
2. Resolve configured input and output paths.
3. Discover supported image files.
4. Read file identity, SHA-256, dimensions, EXIF camera data, and timestamps.
5. Skip images that do not need processing.
6. Run local OCR.
7. Extract color palette, brightness, contrast, and a 3x3 color grid.
8. Build `image_record.json`.
9. Build `timeline.json` and `convert_info.json`.
10. Write normalized image and debug overlay artifacts.
11. Update the internal catalog and run status.
12. Create export ZIPs when processing or download commands request them.

## Skip Behavior

The worker uses source hash, source file identity, generation signature, current output root, and required artifact presence to decide whether an item needs processing.

## Internal State

Internal state is stored in the Docker `app-data` volume by default. It is not part of `settings.json`.

## Scope Boundary

The current pipeline operates on each image independently. Similar-image search, person clustering, and cross-image event merging are outside this product's current responsibility.
