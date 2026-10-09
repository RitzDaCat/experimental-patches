#!/usr/bin/env python3
"""Summarize one bounded KWin latency-capture artifact directory."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path


DIRECT_SCANOUT_REASONS = {
    0: "not_attempted",
    1: "accepted",
    2: "view_hidden",
    3: "no_candidate",
    4: "no_buffer",
    5: "no_dmabuf_attributes",
    6: "early_checks_failed",
    7: "format_unsupported",
    8: "buffer_import_failed",
    9: "scanout_disabled",
    10: "non_primary_plane_disabled",
    11: "modeset_pending",
    12: "shadow_buffer_required",
    13: "color_pipeline_unsupported",
    14: "fractional_source_rect",
    15: "transform_unsupported",
}
REPAINT_DECISIONS = {
    0: "immediate",
    1: "foreground_immediate",
    2: "cadence_deferred",
    3: "stock_deferred",
}


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def distribution(values: list[int]) -> dict[str, int | None]:
    return {
        "count": len(values),
        "p50_ns": percentile(values, 0.50),
        "p95_ns": percentile(values, 0.95),
        "p99_ns": percentile(values, 0.99),
        "max_ns": max(values) if values else None,
    }


def integers(rows: list[dict[str, str]], column: str) -> list[int]:
    result = []
    for row in rows:
        try:
            result.append(int(row[column]))
        except (KeyError, TypeError, ValueError):
            continue
    return result


def differences(
    rows: list[dict[str, str]],
    later: str,
    earlier: str,
    *,
    nonnegative: bool = True,
) -> list[int]:
    result = []
    for row in rows:
        try:
            value = int(row[later]) - int(row[earlier])
        except (KeyError, TypeError, ValueError):
            continue
        if not nonnegative or value >= 0:
            result.append(value)
    return result


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as source:
        return list(csv.DictReader(source))


def read_tsv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def window_bounds(capture: Path) -> tuple[int, int] | None:
    values = capture_metadata(capture)
    try:
        return int(values["start_monotonic_ns"]), int(values["end_monotonic_ns"])
    except (KeyError, ValueError):
        return None


def capture_metadata(capture: Path) -> dict[str, str]:
    values = {}
    try:
        for line in (capture / "window.txt").read_text().splitlines():
            key, value = line.split("=", 1)
            values[key] = value
    except (FileNotFoundError, ValueError):
        pass
    return values


def telemetry_epoch_floor(metadata: dict[str, str]) -> int | None:
    """Old monotonic rows can alias a new capture after reboot; reject their files."""
    floors = []
    # Prefer CLOCK_BOOTTIME: it counts suspended time, CLOCK_MONOTONIC does not.
    # Using the monotonic clock places the derived boot epoch late by the total
    # time suspended, so after a resume this floor rejects files the running
    # compositor is still writing -- cold-path logs such as "kwin *color*.log",
    # written once at pipeline setup, are the ones that actually disappear.
    # Captures recorded before start_boottime_ns existed fall back to the old
    # derivation, which errs toward over-rejecting rather than accepting stale data.
    for key in ("start_boottime_ns", "start_monotonic_ns"):
        try:
            boot_epoch = int(metadata["start_epoch"]) - int(metadata[key]) // 1_000_000_000
        except (KeyError, ValueError):
            continue
        floors.append(boot_epoch - 2)
        break
    try:
        floors.append(int(metadata["kwin_start_epoch"]) - 1)
    except (KeyError, ValueError):
        pass
    return max(floors) if floors else None


def current_telemetry_paths(telemetry: Path, pattern: str, epoch_floor: int | None) -> tuple[list[Path], list[Path]]:
    current = []
    stale = []
    for path in sorted(telemetry.glob(pattern)):
        if epoch_floor is not None and int(path.stat().st_mtime) < epoch_floor:
            stale.append(path)
        else:
            current.append(path)
    return current, stale


def within_window(rows: list[dict[str, str]], column: str, bounds: tuple[int, int] | None) -> list[dict[str, str]]:
    if bounds is None:
        return rows
    start, end = bounds
    selected = []
    for row in rows:
        try:
            if start <= int(row[column]) <= end:
                selected.append(row)
        except (KeyError, TypeError, ValueError):
            continue
    return selected


def distinct_wake_samples(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Collapse rows that share one compositor wake.

    Compositor rows are emitted once per completed frame, but the wake-derived
    columns are stamped from the wake that produced them. When more than one
    frame completes against a single wake, those columns repeat and a naive
    percentile counts one physical wake several times. Frame-derived columns are
    genuinely per-frame and must not be collapsed, so this applies only to
    wake-derived metrics.
    """
    if not rows or "wake sample sequence" not in rows[0]:
        return rows
    seen = set()
    unique = []
    for row in rows:
        try:
            sequence = int(row["wake sample sequence"])
        except (KeyError, TypeError, ValueError):
            unique.append(row)
            continue
        if sequence in seen:
            continue
        seen.add(sequence)
        unique.append(row)
    return unique


def compositor_timestamp_column(rows: list[dict[str, str]]) -> str:
    """Revision 15 rows are completion records; legacy rows are wake samples."""
    if rows and "completion callback timestamp" in rows[0]:
        return "completion callback timestamp"
    return "actual wake timestamp"


def select_compositor_window(
    rows: list[dict[str, str]],
    bounds: tuple[int, int] | None,
) -> tuple[list[dict[str, str]], str]:
    column = compositor_timestamp_column(rows)
    return within_window(rows, column, bounds), column


def has_post_window_row(
    rows: list[dict[str, str]],
    column: str,
    bounds: tuple[int, int] | None,
) -> bool:
    if bounds is None:
        return False
    end = bounds[1]
    return any(value > end for value in integers(rows, column))


def analyze_compositor(path: Path, bounds: tuple[int, int] | None) -> dict:
    all_rows = read_rows(path)
    rows, timestamp_column = select_compositor_window(all_rows, bounds)
    frame_sequences = integers(rows, "frame sequence")
    exact_frame_ids = bool(rows) and len(frame_sequences) == len(rows) and all(
        sequence > 0 for sequence in frame_sequences
    )
    window_flush_proven = exact_frame_ids and has_post_window_row(
        all_rows, timestamp_column, bounds
    )
    wake_rows = distinct_wake_samples(rows)
    ordered_pageflips = sorted(integers(rows, "pageflip timestamp"))
    reason_counts = Counter(DIRECT_SCANOUT_REASONS.get(value, f"unknown_{value}") for value in integers(rows, "direct scanout reason"))
    repaint_counts = Counter(REPAINT_DECISIONS.get(value, f"unknown_{value}") for value in integers(rows, "repaint decision"))
    return {
        "file": path.name,
        "session_rows": len(all_rows),
        "sampled_frames": len(rows),
        "vrr_samples": sum(integers(rows, "vrr")),
        "wake_samples": len(wake_rows),
        "duplicate_wake_rows": len(rows) - len(wake_rows),
        "wake_lateness": distribution(integers(wake_rows, "wake lateness")),
        "raw_render_duration": distribution(integers(rows, "raw render duration")),
        "wake_to_pageflip": distribution(differences(rows, "pageflip timestamp", "actual wake timestamp")),
        "render_end_to_pageflip": distribution(differences(rows, "pageflip timestamp", "render end")),
        "target_error": distribution(differences(
            rows, "pageflip timestamp", "target pageflip timestamp", nonnegative=False
        )),
        "composite_entry_to_frame_creation": distribution(differences(
            rows, "frame created timestamp", "composite start timestamp"
        )),
        "composite_entry_to_pageflip": distribution(differences(
            rows, "pageflip timestamp", "composite start timestamp"
        )),
        "frame_created_to_pageflip": distribution(differences(
            rows, "pageflip timestamp", "frame created timestamp"
        )),
        "frame_created_to_callback": distribution(differences(
            rows, "completion callback timestamp", "frame created timestamp"
        )),
        "pageflip_to_completion_callback": distribution(differences(
            rows, "completion callback timestamp", "pageflip timestamp"
        )),
        "prepaint": distribution(integers(rows, "prepaint duration")),
        "layer_setup": distribution(integers(rows, "layer setup duration")),
        "direct_scanout_prepare": distribution(integers(rows, "direct scanout prepare duration")),
        "render_layers": distribution(
            integers(rows, "render layers duration")
            or integers(rows, "cpu render layers duration")
        ),
        "scene_frame_and_postpaint": distribution(
            integers(rows, "scene frame and postpaint duration")
            or integers(rows, "postpaint duration")
        ),
        "presentation_test_duration": distribution(integers(rows, "presentation test duration")),
        "present_queue_duration": distribution(integers(rows, "present queue duration")),
        "pageflip_cadence": distribution([
            later - earlier
            for earlier, later in zip(
                ordered_pageflips,
                ordered_pageflips[1:],
            )
            if later >= earlier
        ] if window_flush_proven else []),
        "exact_frame_ids": exact_frame_ids,
        "window_flush_proven": window_flush_proven,
        "post_window_rows": sum(
            value > bounds[1] for value in integers(all_rows, timestamp_column)
        ) if bounds else 0,
        "window_timestamp": timestamp_column,
        "direct_scanout_reasons": dict(reason_counts),
        "repaint_decisions": dict(repaint_counts),
        "presentation_fallbacks": sum(integers(rows, "presentation fallbacks")),
    }


def analyze_drm(path: Path, bounds: tuple[int, int] | None) -> dict:
    all_rows = read_rows(path)
    rows = within_window(all_rows, "submit_start_ns", bounds)
    success = integers(rows, "success")
    sequences = integers(rows, "sequence")
    exact_commit_ids = bool(rows) and len(sequences) == len(rows) and all(
        sequence > 0 for sequence in sequences
    ) and bool(all_rows) and "queued_ns" in all_rows[0]
    return {
        "file": path.name,
        "session_rows": len(all_rows),
        "sampled_commits": len(rows),
        "failed_commits": len(success) - sum(success),
        "vrr_samples": sum(integers(rows, "vrr")),
        "ioctl": distribution(integers(rows, "ioctl_ns")),
        "queue_age": distribution(integers(rows, "queue_age_ns")),
        "queue_to_submit": distribution(differences(rows, "submit_start_ns", "queued_ns")),
        "submit_to_pageflip": distribution(differences(rows, "pageflip_timestamp_ns", "submit_end_ns")),
        "pageflip_to_callback": distribution(differences(rows, "callback_ns", "pageflip_timestamp_ns")),
        "target_error": distribution(differences(
            rows, "pageflip_timestamp_ns", "target_ns", nonnegative=False
        )),
        "callback_after_submit": distribution(integers(rows, "callback_after_submit_ns")),
        "readiness_retries": sum(integers(rows, "readiness_retries")),
        "max_queue_depth": max(integers(rows, "queue_depth"), default=0),
        "exact_commit_ids": exact_commit_ids,
        "window_flush_proven": exact_commit_ids and has_post_window_row(
            all_rows, "submit_start_ns", bounds
        ),
        "post_window_rows": sum(
            value > bounds[1] for value in integers(all_rows, "submit_start_ns")
        ) if bounds else 0,
    }


def analyze_input(path: Path, bounds: tuple[int, int] | None) -> dict:
    all_rows = read_rows(path)
    rows = within_window(all_rows, "interval_end_ns", bounds)
    totals = {}
    for event_class in ("motion", "button", "key", "other"):
        count = sum(integers(rows, f"{event_class}_count"))
        age_sum = sum(integers(rows, f"{event_class}_age_sum_ns"))
        totals[event_class] = {
            "sampled_events": count,
            "mean_age_ns": round(age_sum / count) if count else None,
            "max_age_ns": max(integers(rows, f"{event_class}_age_max_ns"), default=None),
        }
    return {
        "file": path.name,
        "session_rows": len(all_rows),
        "windows": len(rows),
        "max_queue_depth": max(integers(rows, "max_queue_depth"), default=0),
        "producer_wait": distribution(integers(rows, "producer_wait_max_ns")),
        "consumer_wait": distribution(integers(rows, "consumer_wait_max_ns")),
        "events": totals,
    }


def format_ns(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.3f} ms"
    if value >= 1_000:
        return f"{value / 1_000:.3f} us"
    return f"{value} ns"


def output_name(path: Path, prefix: str) -> str:
    name = path.stem
    return name.removeprefix(prefix)


def correlate_pipeline(
    compositor_paths: list[Path],
    drm_paths: list[Path],
    bounds: tuple[int, int] | None,
) -> list[dict]:
    reports = []
    drm_by_output = {
        output_name(path, "kwin drm timing "): path
        for path in drm_paths
    }
    for compositor_path in compositor_paths:
        output = output_name(compositor_path, "kwin perf statistics ")
        drm_path = drm_by_output.get(output)
        if drm_path is None:
            continue
        compositor_rows, _ = select_compositor_window(
            read_rows(compositor_path), bounds
        )
        # Use the full current-session DRM file for the join. A compositor
        # completion at a window boundary can legitimately have been submitted
        # just before the boundary.
        drm_rows = read_rows(drm_path)
        drm_by_pageflip: dict[int, list[dict[str, str]]] = {}
        for row in drm_rows:
            try:
                timestamp = int(row["pageflip_timestamp_ns"])
            except (KeyError, TypeError, ValueError):
                continue
            if timestamp:
                drm_by_pageflip.setdefault(timestamp, []).append(row)

        joined: list[tuple[dict[str, str], dict[str, str]]] = []
        eligible_frames = 0
        for compositor_row in compositor_rows:
            try:
                timestamp = int(compositor_row["pageflip timestamp"])
            except (KeyError, TypeError, ValueError):
                continue
            if not timestamp:
                continue
            eligible_frames += 1
            candidates = drm_by_pageflip.get(timestamp)
            if candidates:
                joined.append((compositor_row, candidates.pop(0)))

        def joined_difference(
            later_row_index: int,
            later_column: str,
            earlier_row_index: int,
            earlier_column: str,
        ) -> list[int]:
            values = []
            for pair in joined:
                try:
                    value = int(pair[later_row_index][later_column]) - int(
                        pair[earlier_row_index][earlier_column]
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if value >= 0:
                    values.append(value)
            return values

        reports.append({
            "output": output,
            "eligible_frames": eligible_frames,
            "correlated_frames": len(joined),
            "unmatched_frames": eligible_frames - len(joined),
            "correlation_percent": (
                100.0 * len(joined) / eligible_frames if eligible_frames else None
            ),
            "wake_to_submit": distribution(joined_difference(
                1, "submit_start_ns", 0, "actual wake timestamp"
            )),
            "frame_created_to_submit": distribution(joined_difference(
                1, "submit_start_ns", 0, "frame created timestamp"
            )),
            "render_end_to_submit": distribution(joined_difference(
                1, "submit_start_ns", 0, "render end"
            )),
            "submit_to_pageflip": distribution(joined_difference(
                1, "pageflip_timestamp_ns", 1, "submit_end_ns"
            )),
            "pageflip_to_callback": distribution(joined_difference(
                1, "callback_ns", 1, "pageflip_timestamp_ns"
            )),
            "wake_to_callback": distribution(joined_difference(
                1, "callback_ns", 0, "actual wake timestamp"
            )),
        })
    return reports


def analyze_clock_correlation(capture: Path) -> dict | None:
    path = capture / "clock-correlation.tsv"
    if not path.exists():
        return None
    rows = read_tsv_rows(path)
    brackets = integers(rows, "bracket_ns")
    offsets = differences(
        rows, "realtime_ns", "monotonic_midpoint_ns", nonnegative=False
    )
    return {
        "samples": len(rows),
        "bracket": distribution(brackets),
        "realtime_monotonic_offset_span_ns": (
            max(offsets) - min(offsets) if offsets else None
        ),
    }


def analyze_color_state(capture: Path) -> dict | None:
    result: dict[str, object] = {}
    for phase in ("before", "after"):
        path = capture / f"drm-color-{phase}.txt"
        if not path.exists():
            continue
        lines = path.read_text(errors="replace").splitlines()
        active = [line.strip() for line in lines if "[ACTIVE]" in line]
        non_bypass = [
            line for line in active
            if not line.startswith("choice 0 ") and "Bypass" not in line
        ]
        checksum_path = capture / f"drm-blobs-{phase}.sha256"
        checksums = (
            [line for line in checksum_path.read_text().splitlines() if line]
            if checksum_path.exists()
            else []
        )
        result[phase] = {
            "active_choices": active,
            "active_non_bypass_planes": len(non_bypass),
            "captured_blob_count": len(checksums),
        }
    return result or None


def record_headers(path: Path) -> list[dict[str, str]]:
    records = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("record="):
            continue
        fields = {}
        for token in line.split():
            if "=" in token:
                key, value = token.split("=", 1)
                fields[key] = value
        records.append(fields)
    return records


def analyze_color_telemetry(paths: list[Path]) -> list[dict]:
    reports = []
    for path in paths:
        rows = record_headers(path)
        durations = integers(rows, "duration_ns")
        report = {
            "file": path.name,
            "records": len(rows),
            "duration": distribution(durations),
        }
        if path.name == "kwin drm color match.log":
            report["matched"] = sum(integers(rows, "matched"))
            report["residual_inverse_scaling"] = sum(
                integers(rows, "residual_inverse_scaling")
            )
            report["compensated_non_bypassable"] = sum(
                integers(rows, "compensated_non_bypassable")
            )
        reports.append(report)
    return reports


def render_markdown(report: dict) -> str:
    lines = ["# Bounded latency capture summary", ""]
    if report["warnings"]:
        lines.extend(["## Capture warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
        lines.append("")
    for item in report["compositor"]:
        lines.extend([
            f"## Compositor: {item['file']}", "",
            f"- Window samples / session rows: {item['sampled_frames']} / {item['session_rows']} ({item['vrr_samples']} VRR)",
            f"- Exact frame IDs / window flush proven: {'yes' if item['exact_frame_ids'] else 'no'} / {'yes' if item['window_flush_proven'] else 'no'}",
            f"- Window selector / post-window rows: {item['window_timestamp']} / {item['post_window_rows']}",
            f"- Distinct wake samples / duplicate frame rows collapsed: {item['wake_samples']} / {item['duplicate_wake_rows']}",
            f"- Wake lateness p50/p95/p99/max: {format_ns(item['wake_lateness']['p50_ns'])} / {format_ns(item['wake_lateness']['p95_ns'])} / {format_ns(item['wake_lateness']['p99_ns'])} / {format_ns(item['wake_lateness']['max_ns'])}",
            f"- Render duration p50/p95/p99: {format_ns(item['raw_render_duration']['p50_ns'])} / {format_ns(item['raw_render_duration']['p95_ns'])} / {format_ns(item['raw_render_duration']['p99_ns'])}",
            f"- Wake-to-pageflip p50/p95/p99: {format_ns(item['wake_to_pageflip']['p50_ns'])} / {format_ns(item['wake_to_pageflip']['p95_ns'])} / {format_ns(item['wake_to_pageflip']['p99_ns'])}",
            f"- Render-end-to-pageflip p50/p95/p99: {format_ns(item['render_end_to_pageflip']['p50_ns'])} / {format_ns(item['render_end_to_pageflip']['p95_ns'])} / {format_ns(item['render_end_to_pageflip']['p99_ns'])}",
            f"- Composite-entry-to-frame-created/pageflip p99: {format_ns(item['composite_entry_to_frame_creation']['p99_ns'])} / {format_ns(item['composite_entry_to_pageflip']['p99_ns'])}",
            f"- Frame-created-to-pageflip/callback p99: {format_ns(item['frame_created_to_pageflip']['p99_ns'])} / {format_ns(item['frame_created_to_callback']['p99_ns'])}",
            f"- Pageflip-to-compositor-callback p99: {format_ns(item['pageflip_to_completion_callback']['p99_ns'])}",
            f"- Pageflip cadence p50/p95/p99: {format_ns(item['pageflip_cadence']['p50_ns'])} / {format_ns(item['pageflip_cadence']['p95_ns'])} / {format_ns(item['pageflip_cadence']['p99_ns'])}",
            f"- Phase p99 prepaint/layer setup/scanout prepare/render layers/scene frame plus postpaint: {format_ns(item['prepaint']['p99_ns'])} / {format_ns(item['layer_setup']['p99_ns'])} / {format_ns(item['direct_scanout_prepare']['p99_ns'])} / {format_ns(item['render_layers']['p99_ns'])} / {format_ns(item['scene_frame_and_postpaint']['p99_ns'])}",
            "- Direct-scanout preparation is nested inside layer setup; these phase values must not be summed.",
            f"- Presentation-test p99: {format_ns(item['presentation_test_duration']['p99_ns'])}",
            f"- Present-queue p99: {format_ns(item['present_queue_duration']['p99_ns'])}",
            f"- Direct-scanout reasons: {item['direct_scanout_reasons']}",
            f"- Repaint decisions: {item['repaint_decisions']}", "",
        ])
    for item in report["drm"]:
        lines.extend([
            f"## DRM: {item['file']}", "",
            f"- Window commits / session rows / failures: {item['sampled_commits']} / {item['session_rows']} / {item['failed_commits']}",
            f"- Exact commit IDs / window flush proven / post-window rows: {'yes' if item['exact_commit_ids'] else 'no'} / {'yes' if item['window_flush_proven'] else 'no'} / {item['post_window_rows']}",
            f"- IOCTL p50/p95/p99: {format_ns(item['ioctl']['p50_ns'])} / {format_ns(item['ioctl']['p95_ns'])} / {format_ns(item['ioctl']['p99_ns'])}",
            f"- Queue age p99: {format_ns(item['queue_age']['p99_ns'])}",
            f"- Queue-to-submit p99: {format_ns(item['queue_to_submit']['p99_ns'])}",
            f"- Submit-to-pageflip p50/p95/p99: {format_ns(item['submit_to_pageflip']['p50_ns'])} / {format_ns(item['submit_to_pageflip']['p95_ns'])} / {format_ns(item['submit_to_pageflip']['p99_ns'])}",
            f"- Pageflip-event-to-callback p99: {format_ns(item['pageflip_to_callback']['p99_ns'])}",
            f"- Callback-after-submit p99: {format_ns(item['callback_after_submit']['p99_ns'])}",
            f"- Readiness retries / max queue depth: {item['readiness_retries']} / {item['max_queue_depth']}", "",
        ])
    for item in report["pipeline"]:
        lines.extend([
            f"## Correlated frame path: {item['output']}", "",
            f"- Exact DRM-pageflip joins / eligible / unmatched: {item['correlated_frames']} / {item['eligible_frames']} / {item['unmatched_frames']} ({item['correlation_percent']:.2f}% coverage)" if item["correlation_percent"] is not None else "- Exact DRM-pageflip joins / eligible / unmatched: 0 / 0 / 0 (n/a coverage)",
            f"- Wake-to-submit p50/p95/p99: {format_ns(item['wake_to_submit']['p50_ns'])} / {format_ns(item['wake_to_submit']['p95_ns'])} / {format_ns(item['wake_to_submit']['p99_ns'])}",
            f"- Frame-created-to-submit p50/p95/p99: {format_ns(item['frame_created_to_submit']['p50_ns'])} / {format_ns(item['frame_created_to_submit']['p95_ns'])} / {format_ns(item['frame_created_to_submit']['p99_ns'])}",
            f"- Render-end-to-submit p50/p95/p99: {format_ns(item['render_end_to_submit']['p50_ns'])} / {format_ns(item['render_end_to_submit']['p95_ns'])} / {format_ns(item['render_end_to_submit']['p99_ns'])}",
            f"- Submit-to-pageflip p50/p95/p99: {format_ns(item['submit_to_pageflip']['p50_ns'])} / {format_ns(item['submit_to_pageflip']['p95_ns'])} / {format_ns(item['submit_to_pageflip']['p99_ns'])}",
            f"- Pageflip-to-callback p50/p95/p99: {format_ns(item['pageflip_to_callback']['p50_ns'])} / {format_ns(item['pageflip_to_callback']['p95_ns'])} / {format_ns(item['pageflip_to_callback']['p99_ns'])}",
            f"- Wake-to-callback p50/p95/p99: {format_ns(item['wake_to_callback']['p50_ns'])} / {format_ns(item['wake_to_callback']['p95_ns'])} / {format_ns(item['wake_to_callback']['p99_ns'])}",
            "",
        ])
    for item in report["input"]:
        lines.extend([
            "## Input queue", "",
            f"- Capture windows / session rows / max queue depth: {item['windows']} / {item['session_rows']} / {item['max_queue_depth']}",
            f"- Producer-wait max-window p99: {format_ns(item['producer_wait']['p99_ns'])}",
            f"- Consumer-wait max-window p99: {format_ns(item['consumer_wait']['p99_ns'])}",
            f"- Event ages: {item['events']}", "",
        ])
    if not any(report[key] for key in ("compositor", "drm", "input")):
        lines.append("No valid KWin telemetry CSV files were found.")
    if report["clock"]:
        clock = report["clock"]
        lines.extend([
            "## Clock correlation", "",
            f"- Samples: {clock['samples']}",
            f"- Read bracket p50/p95/max: {format_ns(clock['bracket']['p50_ns'])} / {format_ns(clock['bracket']['p95_ns'])} / {format_ns(clock['bracket']['max_ns'])}",
            f"- Realtime-to-monotonic offset span: {format_ns(clock['realtime_monotonic_offset_span_ns'])}",
            "",
        ])
    if report["color"]:
        lines.extend([
            "## DRM color state", "",
            f"- Before: {report['color'].get('before', {})}",
            f"- After: {report['color'].get('after', {})}",
            "",
        ])
    for item in report["color_telemetry"]:
        lines.extend([
            f"## Color telemetry: {item['file']}", "",
            f"- Cold-path records: {item['records']}",
            f"- Duration p50/p95/p99/max: {format_ns(item['duration']['p50_ns'])} / {format_ns(item['duration']['p95_ns'])} / {format_ns(item['duration']['p99_ns'])} / {format_ns(item['duration']['max_ns'])}",
        ])
        if "matched" in item:
            lines.extend([
                f"- Matched / residual inverse scaling / compensated mandatory blocks: {item['matched']} / {item['residual_inverse_scaling']} / {item['compensated_non_bypassable']}",
            ])
        lines.append("")
    lines.extend([
        "The precision timing window excludes the later NVIDIA and PipeWire polling phase.",
        "",
        "Exact capture is diagnostic instrumentation: clock reads and CSV formatting can perturb later frames. Use these boundaries for attribution, then prove performance with capture disabled and a matched external or application-side A/B.",
        "",
        "The DRM pageflip timestamp marks the kernel presentation event and callback timing ends at KWin's event handling. Neither is a physical photon measurement.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    telemetry = args.capture / "kwin-telemetry"
    metadata = capture_metadata(args.capture)
    bounds = window_bounds(args.capture)
    epoch_floor = telemetry_epoch_floor(metadata)
    compositor_paths, stale_compositor = current_telemetry_paths(telemetry, "kwin perf statistics *.csv", epoch_floor)
    drm_paths, stale_drm = current_telemetry_paths(telemetry, "kwin drm timing *.csv", epoch_floor)
    input_paths, stale_input = current_telemetry_paths(telemetry, "kwin input latency.csv", epoch_floor)
    color_paths, stale_color = current_telemetry_paths(telemetry, "kwin *color*.log", epoch_floor)
    stale_paths = stale_compositor + stale_drm + stale_input + stale_color
    warnings = []
    if stale_paths:
        warnings.append(
            "Rejected stale KWin telemetry from an earlier boot or compositor session: "
            + ", ".join(path.name for path in stale_paths)
        )
    compositor_reports = [analyze_compositor(path, bounds) for path in compositor_paths]
    drm_reports = [analyze_drm(path, bounds) for path in drm_paths]
    pipeline_reports = correlate_pipeline(compositor_paths, drm_paths, bounds)
    for item in compositor_reports:
        if item["exact_frame_ids"] and bounds and not item["window_flush_proven"]:
            warnings.append(
                f"{item['file']}: exact frame IDs are present, but no post-window row proves that the in-window buffered tail reached disk."
            )
    for item in drm_reports:
        if item["exact_commit_ids"] and bounds and not item["window_flush_proven"]:
            warnings.append(
                f"{item['file']}: exact commit IDs are present, but no post-window row proves that the in-window buffered tail reached disk."
            )
    for item in pipeline_reports:
        if item["unmatched_frames"]:
            warnings.append(
                f"{item['output']}: {item['unmatched_frames']} of {item['eligible_frames']} compositor frames did not join to a DRM record by exact pageflip timestamp."
            )
    report = {
        "warnings": warnings,
        "compositor": compositor_reports,
        "drm": drm_reports,
        "input": [analyze_input(path, bounds) for path in input_paths],
        "pipeline": pipeline_reports,
        "clock": analyze_clock_correlation(args.capture),
        "color": analyze_color_state(args.capture),
        "color_telemetry": analyze_color_telemetry(color_paths),
    }
    print(json.dumps(report, indent=2) if args.json else render_markdown(report), end="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
