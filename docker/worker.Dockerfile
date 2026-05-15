FROM mcr.microsoft.com/dotnet/sdk:10.0 AS health-build

WORKDIR /src

COPY health/TimelineForImage.Health/TimelineForImage.Health.csproj health/TimelineForImage.Health/
RUN dotnet restore health/TimelineForImage.Health/TimelineForImage.Health.csproj

COPY health/TimelineForImage.Health/ health/TimelineForImage.Health/
RUN dotnet publish health/TimelineForImage.Health/TimelineForImage.Health.csproj -c Release -o /app/health --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace/worker/src
ENV TIMELINE_FOR_IMAGE_IN_DOCKER=1
ENV TIMELINE_FOR_IMAGE_PYTHON=/opt/tfi-python/bin/python
ENV PATH=/opt/tfi-python/bin:$PATH

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-jpn \
    && rm -rf /var/lib/apt/lists/*

COPY worker/requirements.txt /workspace/worker/requirements.txt
RUN python3 -m venv /opt/tfi-python \
    && /opt/tfi-python/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/tfi-python/bin/pip install --no-cache-dir -r /workspace/worker/requirements.txt

COPY worker/src /workspace/worker/src
COPY --from=health-build /app/health /app/health
COPY docker/entrypoint.sh /usr/local/bin/tfi-entrypoint
RUN chmod +x /usr/local/bin/tfi-entrypoint

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=5).read()"]

ENTRYPOINT ["tfi-entrypoint"]
CMD ["idle"]
