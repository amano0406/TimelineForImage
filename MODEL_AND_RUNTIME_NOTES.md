# Model and Runtime Notes

TimelineForImage currently uses local image metadata extraction and local Tesseract OCR.

No external image API is called by the default worker.

OCR text is not privacy-redacted. Person identity recognition and face recognition are not performed.
