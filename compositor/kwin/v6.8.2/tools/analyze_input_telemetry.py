#!/usr/bin/env python3

"""Summarize bounded KWin input queue telemetry captures."""

import argparse
import csv
import json
import math
from pathlib import Path


SCHEMA_VERSIONS = (1, 2)
BUCKETS = (
    ("le_1us", 1),
    ("le_2us", 2),
    ("le_4us", 4),
    ("le_8us", 8),
    ("le_16us", 16),
    ("le_32us", 32),
    ("le_64us", 64),
    ("le_125us", 125),
    ("le_250us", 250),
    ("le_500us", 500),
    ("le_1000us", 1000),
    ("le_2000us", 2000),
    ("le_4000us", 4000),
    ("le_8000us", 8000),
    ("le_16000us", 16000),
    ("gt_16000us", None),
)
DISTRIBUTIONS = ("producer_wait", "producer_hold", "consumer_wait", "consumer_hold")
EVENT_CLASSES = ("motion", "button", "key", "other")
PERCENTILES = (50, 95, 99, 99.9)


def _integer(row, name):
    try:
        value = int(row[name])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid or missing integer field {name!r}") from error
    if value < 0:
        raise ValueError(f"negative value in field {name!r}")
    return value


def load_rows(paths):
    rows = []
    for path in paths:
        with Path(path).open(newline="") as stream:
            reader = csv.DictReader(stream)
            for row in reader:
                if _integer(row, "schema_version") not in SCHEMA_VERSIONS:
                    raise ValueError(f"unsupported schema in {path}")
                rows.append(row)
    if not rows:
        raise ValueError("capture contains no telemetry rows")
    return rows


def _aggregate_distribution(rows, prefix, age=False):
    count_name = f"{prefix}_count"
    sum_name = f"{prefix}_{'age_' if age else ''}sum_ns"
    max_name = f"{prefix}_{'age_' if age else ''}max_ns"
    bucket_prefix = f"{prefix}_{'age_' if age else ''}"
    count = sum(_integer(row, count_name) for row in rows)
    total_ns = sum(_integer(row, sum_name) for row in rows)
    maximum_ns = max(_integer(row, max_name) for row in rows)
    histogram = [sum(_integer(row, bucket_prefix + suffix) for row in rows) for suffix, _ in BUCKETS]
    if sum(histogram) != count:
        raise ValueError(f"histogram count mismatch for {prefix}")
    return {
        "count": count,
        "total_ns": total_ns,
        "max_ns": maximum_ns,
        "histogram": histogram,
    }


def percentile_upper_us(distribution, percentile):
    count = distribution["count"]
    if count == 0:
        return None
    target = max(1, math.ceil(count * percentile / 100))
    cumulative = 0
    for bucket_count, (_, upper_us) in zip(distribution["histogram"], BUCKETS):
        cumulative += bucket_count
        if cumulative >= target:
            return upper_us
    raise ValueError("histogram does not cover distribution")


def _distribution_summary(distribution):
    count = distribution["count"]
    return {
        "count": count,
        "mean_us": distribution["total_ns"] / count / 1000 if count else None,
        "max_us": distribution["max_ns"] / 1000 if count else None,
        "percentile_upper_us": {
            str(percentile): percentile_upper_us(distribution, percentile)
            for percentile in PERCENTILES
        },
    }


def summarize(rows):
    schema_versions = {_integer(row, "schema_version") for row in rows}
    if len(schema_versions) != 1:
        raise ValueError("cannot combine different telemetry schemas")
    schema_version = schema_versions.pop()
    sample_divisors = {_integer(row, "sample_divisor") for row in rows} if schema_version >= 2 else {1}
    if len(sample_divisors) != 1 or 0 in sample_divisors:
        raise ValueError("capture has inconsistent sample divisors")
    sample_divisor = sample_divisors.pop()
    duration_ns = sum(_integer(row, "interval_duration_ns") for row in rows)
    producer_batches = sum(_integer(row, "producer_batches") for row in rows)
    events_queued = sum(_integer(row, "events_queued") for row in rows)
    consumer_batches = sum(_integer(row, "consumer_batches") for row in rows)
    events_processed = sum(_integer(row, "events_processed") for row in rows)
    motions_coalesced = sum(_integer(row, "motions_coalesced") for row in rows)
    motions_queued = sum(_integer(row, "motions_queued") for row in rows) if schema_version >= 2 else None
    distributions = {
        name: _aggregate_distribution(rows, name)
        for name in DISTRIBUTIONS
    }
    event_ages = {
        name: _aggregate_distribution(rows, name, age=True)
        for name in EVENT_CLASSES
    }
    motion_denominator = motions_queued if motions_queued is not None else event_ages["motion"]["count"]
    duration_s = duration_ns / 1_000_000_000
    return {
        "schema_version": schema_version,
        "sample_divisor": sample_divisor,
        "interval_rows": len(rows),
        "duration_s": duration_s,
        "producer_batches": producer_batches,
        "events_queued": events_queued,
        "consumer_batches": consumer_batches,
        "events_processed": events_processed,
        "events_per_second": events_processed / duration_s if duration_s else 0,
        "events_per_consumer_batch": events_processed / consumer_batches if consumer_batches else 0,
        "motions_coalesced": motions_coalesced,
        "motions_queued": motions_queued,
        "motion_coalescing_ratio": motions_coalesced / motion_denominator if motion_denominator else 0,
        "max_queue_depth": max(_integer(row, "max_queue_depth") for row in rows),
        "distributions": {name: _distribution_summary(value) for name, value in distributions.items()},
        "event_queue_age": {name: _distribution_summary(value) for name, value in event_ages.items()},
    }


def _format_percentile(value, count):
    if count == 0:
        return "n/a"
    return ">16000" if value is None else f"<={value:g}"


def format_text(summary):
    lines = [
        "KWin input queue telemetry",
        f"  schema: {summary['schema_version']}, timing/motion sample divisor: {summary['sample_divisor']}",
        f"  duration: {summary['duration_s']:.2f} s in {summary['interval_rows']} intervals",
        f"  events: {summary['events_processed']} processed ({summary['events_per_second']:.1f}/s)",
        f"  batches: {summary['consumer_batches']} consumer, {summary['events_per_consumer_batch']:.2f} events/batch",
        f"  maximum queue depth: {summary['max_queue_depth']}",
        f"  coalesced motions: {summary['motions_coalesced']} ({summary['motion_coalescing_ratio'] * 100:.2f}% of motion reports)",
        "",
        "Mutex timing (microseconds; percentiles are histogram upper bounds)",
    ]
    for name in DISTRIBUTIONS:
        item = summary["distributions"][name]
        percentiles = item["percentile_upper_us"]
        lines.append(
            f"  {name}: count={item['count']} mean={item['mean_us'] or 0:.3f} "
            f"p95={_format_percentile(percentiles['95'], item['count'])} "
            f"p99={_format_percentile(percentiles['99'], item['count'])} "
            f"p99.9={_format_percentile(percentiles['99.9'], item['count'])} max={item['max_us'] or 0:.3f}"
        )
    lines.extend(("", "Queue age at drain start (microseconds)"))
    for name in EVENT_CLASSES:
        item = summary["event_queue_age"][name]
        percentiles = item["percentile_upper_us"]
        lines.append(
            f"  {name}: count={item['count']} mean={item['mean_us'] or 0:.3f} "
            f"p95={_format_percentile(percentiles['95'], item['count'])} "
            f"p99={_format_percentile(percentiles['99'], item['count'])} "
            f"p99.9={_format_percentile(percentiles['99.9'], item['count'])} max={item['max_us'] or 0:.3f}"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", help="kwin input latency.csv capture files")
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    args = parser.parse_args()
    try:
        summary = summarize(load_rows(args.captures))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(format_text(summary))


if __name__ == "__main__":
    main()
