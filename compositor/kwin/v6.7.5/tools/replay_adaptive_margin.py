#!/usr/bin/env python3

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.adaptive_margin import AdaptiveMarginController, PATHS  # noqa: E402


PATH_BY_NUMBER = {0: "vsync", 1: "adaptive-sync", 2: "async", 3: "adaptive-async"}


def integer(row, key, default=0):
    value = row.get(key)
    return default if value in (None, "") else int(value)


def row_path(row):
    if "adaptive margin path" in row:
        return PATH_BY_NUMBER[integer(row, "adaptive margin path")]
    vrr = integer(row, "vrr") != 0
    tearing = integer(row, "tearing") != 0
    if vrr and tearing:
        return "adaptive-async"
    if vrr:
        return "adaptive-sync"
    if tearing:
        return "async"
    return "vsync"


def replay(path):
    controller = None
    seen_sequences = set()
    sample_count = 0
    has_sequence = False
    sampled_telemetry = False

    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if integer(row, "telemetry sample divisor", 1) > 1:
                sampled_telemetry = True
            if None in row.values() or not integer(row, "wake sample valid"):
                continue
            if "wake sample trained" in row and not integer(row, "wake sample trained"):
                continue
            if "wake sample sequence" in row:
                has_sequence = True
                sequence = integer(row, "wake sample sequence")
                if sequence in seen_sequences:
                    continue
                seen_sequences.add(sequence)
            row_refresh_ns = integer(row, "refresh duration")
            # A refresh change discards learned state for every path, mirroring
            # resetAdaptiveCompositorSchedulingMargins in renderloop.cpp.
            if controller is None or row_refresh_ns != controller.refresh_ns:
                controller = AdaptiveMarginController(row_refresh_ns)
            controller.sample(row_path(row), integer(row, "wake lateness"))
            sample_count += 1

    if sampled_telemetry:
        print(f"{path}: offline replay skipped because telemetry is sampled")
        print("  set KWIN_COMPOSITOR_TELEMETRY_SAMPLE_DIVISOR=1 for an exact replay capture")
        return

    if controller is None:
        print(f"{path}: no valid timer wake samples")
        return

    print(f"{path}: replayed {sample_count} valid timer wake samples")
    if not has_sequence:
        print("  legacy trace: repeated frame rows cannot be deduplicated exactly")
    for name in PATHS:
        state = controller.states[name]
        print(
            f"  {name:16s} margin={state.margin_ns / 1_000:7.0f} us "
            f"window={state.sample_count:3d}/256 warmed={int(state.warmed_up)}"
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {sys.argv[0]} CSV [CSV ...]")
    for argument in sys.argv[1:]:
        replay(Path(argument).expanduser())
