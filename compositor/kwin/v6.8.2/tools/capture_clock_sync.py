#!/usr/bin/env python3
"""Emit tightly bracketed clock samples for cross-source timestamp correlation."""

from __future__ import annotations

import argparse
import os
import time


CLOCKS = (
    ("realtime", time.CLOCK_REALTIME),
    ("monotonic", time.CLOCK_MONOTONIC),
    ("monotonic_raw", time.CLOCK_MONOTONIC_RAW),
    ("boottime", time.CLOCK_BOOTTIME),
)


def sample(label: str, sequence: int) -> str:
    # Bracket every non-monotonic read with CLOCK_MONOTONIC. The midpoint is a
    # bounded estimate; bracket_ns reports the uncertainty of that mapping.
    before = time.monotonic_ns()
    values = {name: time.clock_gettime_ns(clock_id) for name, clock_id in CLOCKS}
    after = time.monotonic_ns()
    midpoint = before + (after - before) // 2
    return "\t".join(
        str(value)
        for value in (
            label,
            sequence,
            os.getpid(),
            before,
            after,
            after - before,
            midpoint,
            values["realtime"],
            values["monotonic"],
            values["monotonic_raw"],
            values["boottime"],
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--header", action="store_true")
    args = parser.parse_args()
    if args.samples < 1 or args.samples > 1024:
        parser.error("--samples must be in [1, 1024]")
    if args.header:
        print(
            "label\tsequence\tpid\tmonotonic_before_ns\tmonotonic_after_ns"
            "\tbracket_ns\tmonotonic_midpoint_ns\trealtime_ns\tmonotonic_ns"
            "\tmonotonic_raw_ns\tboottime_ns"
        )
    for sequence in range(args.samples):
        print(sample(args.label, sequence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
