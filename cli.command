#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT="${TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT:-/mnt/c}"
docker compose up -d --build worker
docker compose exec -T worker python -m timeline_for_image_worker "$@"
