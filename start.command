#!/usr/bin/env bash
set -euo pipefail
# WSL/Linux back door. Windows users should prefer start.ps1.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
export TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT="${TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT:-/mnt/c}"
export TIMELINE_FOR_IMAGE_OUTPUT_MOUNT="${TIMELINE_FOR_IMAGE_OUTPUT_MOUNT:-/mnt/c/Users/amano/image}"
exec docker compose --profile worker run --rm worker "$@"
