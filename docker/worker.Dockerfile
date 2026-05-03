FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace/worker/src
ENV TIMELINE_FOR_IMAGE_IN_DOCKER=1

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-jpn \
    && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt /workspace/worker/requirements.txt
RUN pip install --no-cache-dir -r /workspace/worker/requirements.txt

COPY worker/src /workspace/worker/src

ENTRYPOINT ["python", "-m", "timeline_for_image_worker"]
CMD ["serve"]
