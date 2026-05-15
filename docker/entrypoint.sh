#!/bin/sh
set -eu

dotnet /app/health/TimelineForImage.Health.dll &
health_pid="$!"

cleanup() {
    kill "$health_pid" 2>/dev/null || true
    wait "$health_pid" 2>/dev/null || true
}

trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

if [ "$#" -eq 0 ] || [ "${1:-}" = "idle" ]; then
    wait "$health_pid"
    exit $?
fi

python -m timeline_for_image_worker "$@"
