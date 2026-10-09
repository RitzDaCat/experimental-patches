#!/usr/bin/env python3

import csv
import math
import sys
from pathlib import Path


def percentile(values, p):
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def summarize(name, values, scale=1_000.0, unit="us"):
    values = [value for value in values if math.isfinite(value)]
    if not values:
        print(f"{name:30s} no data")
        return
    fields = (("p50", 0.50), ("p95", 0.95), ("p99", 0.99), ("p99.9", 0.999))
    rendered = " ".join(f"{label}={percentile(values, p) / scale:8.3f}" for label, p in fields)
    print(f"{name:30s} {rendered} max={max(values) / scale:8.3f} {unit}")


def read_rows(path):
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                yield {key: int(value) for key, value in row.items()}
            except (TypeError, ValueError):
                continue


def unique_trained_wake_samples(rows):
    """Return one row per actual timer dispatch, not one per completed frame."""
    if not rows or "wake sample sequence" not in rows[0]:
        return [row for row in rows if row.get("wake sample valid", 0)]

    samples = {}
    for row in rows:
        if row.get("wake sample valid", 0) and row.get("wake sample trained", 0):
            samples[row["wake sample sequence"]] = row
    return list(samples.values())


def telemetry_sample_divisor(rows):
    divisors = {row.get("telemetry sample divisor", 1) for row in rows}
    if len(divisors) != 1 or min(divisors) < 1:
        raise ValueError("capture has inconsistent telemetry sample divisors")
    return divisors.pop()


def main(paths):
    for path_text in paths:
        path = Path(path_text).expanduser()
        rows = list(read_rows(path))
        print(f"\n{path}: {len(rows)} logged frame rows")
        if not rows:
            continue
        try:
            sample_divisor = telemetry_sample_divisor(rows)
        except ValueError as error:
            print(error)
            continue
        print(f"telemetry sample divisor: {sample_divisor}")

        required = {
            "desired wake timestamp",
            "armed wake timestamp",
            "actual wake timestamp",
            "wake lateness",
            "schedule deficit",
            "compositor scheduling margin",
        }
        missing = required.difference(rows[0])
        if missing:
            print("Not an instrumented 3.2 CSV; missing: " + ", ".join(sorted(missing)))
            continue

        summarize("timer wake lateness", [row["wake lateness"] for row in rows])
        summarize("already-late schedule deficit", [row["schedule deficit"] for row in rows])
        summarize("applied scheduler margin", [row["compositor scheduling margin"] for row in rows])
        summarize("render duration", [row["render end"] - row["render start"] for row in rows])
        summarize("predicted render time", [row["predicted render time"] for row in rows])
        summarize("DRM safety margin", [row["safety margin"] for row in rows])
        summarize("render-start lead to target", [row["target pageflip timestamp"] - row["render start"] for row in rows])
        summarize("pageflip minus target", [row["pageflip timestamp"] - row["target pageflip timestamp"] for row in rows])

        if sample_divisor == 1:
            timestamps = [row["pageflip timestamp"] for row in rows]
            intervals = [right - left for left, right in zip(timestamps, timestamps[1:]) if right >= left]
            summarize("presented frame interval", intervals, scale=1_000_000.0, unit="ms")
        else:
            print("presented frame interval       unavailable in sampled telemetry")

        late_250us = sum(row["pageflip timestamp"] - row["target pageflip timestamp"] > 250_000 for row in rows)
        late_1ms = sum(row["pageflip timestamp"] - row["target pageflip timestamp"] > 1_000_000 for row in rows)
        deficits = sum(row["schedule deficit"] > 0 for row in rows)
        print(f"target lateness >250 us         {late_250us:8d} ({100 * late_250us / len(rows):6.3f}%)")
        print(f"target lateness >1 ms           {late_1ms:8d} ({100 * late_1ms / len(rows):6.3f}%)")
        print(f"deadline already past at arm    {deficits:8d} ({100 * deficits / len(rows):6.3f}%)")
        margins = sorted({row["compositor scheduling margin"] for row in rows})
        if len(margins) <= 8:
            rendered_margins = ", ".join(f"{value / 1_000:.0f} us" for value in margins)
        else:
            rendered_margins = f"{margins[0] / 1_000:.0f}..{margins[-1] / 1_000:.0f} us ({len(margins)} values)"
        print("applied compositor margins: " + rendered_margins)

        adaptive_column = "adaptive compositor scheduling margin"
        if adaptive_column in rows[0]:
            valid_rows = unique_trained_wake_samples(rows)
            summarize("learned adaptive margin", [row[adaptive_column] for row in valid_rows])
            mode_names = {0: "fixed", 1: "shadow", 2: "adaptive"}
            modes = sorted({row.get("compositor margin mode", -1) for row in rows})
            print("compositor margin modes: " + ", ".join(mode_names.get(mode, f"unknown({mode})") for mode in modes))
            if "experiment kernel allowed" in rows[0]:
                gate_values = sorted({row["experiment kernel allowed"] for row in rows})
                print("experiment kernel gate: " + ("active" if gate_values == [1] else f"unexpected values {gate_values}"))
            print(f"valid adaptive wake samples   {len(valid_rows):8d} ({100 * len(valid_rows) / len(rows):6.3f}%)")
            if "adaptive margin path" in rows[0]:
                path_names = {0: "vsync", 1: "adaptive-sync", 2: "async", 3: "adaptive-async"}
                for path_number in sorted({row["adaptive margin path"] for row in valid_rows}):
                    path_rows = [row for row in valid_rows if row["adaptive margin path"] == path_number]
                    path_name = path_names.get(path_number, f"unknown({path_number})")
                    margins = [row[adaptive_column] for row in path_rows]
                    stalls = max((row.get("adaptive external stalls", 0) for row in path_rows), default=0)
                    warmed = any(row.get("adaptive state warmed", 0) for row in path_rows)
                    print(
                        f"  {path_name:16s} samples={len(path_rows):6d} "
                        f"margin={margins[-1] / 1_000:7.0f} us "
                        f"range={min(margins) / 1_000:.0f}..{max(margins) / 1_000:.0f} us "
                        f"warmed={int(warmed)} max-window-stalls={stalls}"
                    )
            if valid_rows:
                learned = [row[adaptive_column] for row in valid_rows]
                changes = sum(left != right for left, right in zip(learned, learned[1:]))
                print(
                    "adaptive margin first/last: "
                    f"{learned[0] / 1_000:.0f}/{learned[-1] / 1_000:.0f} us; "
                    f"min/max: {min(learned) / 1_000:.0f}/{max(learned) / 1_000:.0f} us; "
                    f"changes: {changes}"
                )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(f"usage: {sys.argv[0]} CSV [CSV ...]")
    main(sys.argv[1:])
