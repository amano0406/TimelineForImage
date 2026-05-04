# Safety

[Back to README](../README.md)

These notes affect normal operation on real image folders.

## Source Images

TimelineForImage does not edit source images. Generated artifacts are written under `outputRoot`.

`items remove` deletes generated item artifacts and catalog entries only. It does not delete source image files.

## Exports

Download ZIPs contain generated records and metadata. They do not include original source image files.

## OCR Text

OCR text is preserved in generated records. The product does not mask OCR text for privacy.

## Person Recognition

The product does not perform person identity recognition, face recognition, age inference, gender inference, or person clustering.

## External Services

The default worker does not send images to external APIs.
