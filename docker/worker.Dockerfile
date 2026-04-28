FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/worker/src
ENV TIMELINE_FOR_IMAGE_IN_DOCKER=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-jpn \
    && rm -rf /var/lib/apt/lists/*

COPY worker/requirements-worker.txt /app/worker/requirements-worker.txt
RUN pip install --no-cache-dir -r /app/worker/requirements-worker.txt

COPY worker/src /app/worker/src

ENTRYPOINT ["python", "-m", "timeline_for_image_worker"]
CMD ["doctor"]
