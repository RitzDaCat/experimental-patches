#!/usr/bin/env bash

set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
pattern="$root/tools/color-validation-pattern.ppm"

command -v mpv >/dev/null || {
    printf 'mpv is required for the fullscreen color validation pattern\n' >&2
    exit 1
}

exec mpv \
    --no-config \
    --fullscreen \
    --keep-open=yes \
    --image-display-duration=inf \
    --loop-file=inf \
    --osd-level=0 \
    --scale=nearest \
    --dscale=nearest \
    --cscale=nearest \
    --video-output-levels=full \
    --target-colorspace-hint=no \
    --target-prim=bt.709 \
    --target-trc=srgb \
    "$pattern"
