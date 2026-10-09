import unittest

from tools import analyze_input_telemetry as telemetry


def capture_row(schema_version=2):
    row = {
        "schema_version": str(schema_version),
        "interval_duration_ns": "1000000000",
        "producer_batches": "100",
        "events_queued": "120",
        "motions_queued": "120",
        "consumer_batches": "90",
        "events_processed": "120",
        "motions_coalesced": "20",
        "max_queue_depth": "4",
    }
    if schema_version >= 2:
        row["sample_divisor"] = "64"
    for prefix in telemetry.DISTRIBUTIONS:
        row[f"{prefix}_count"] = "100"
        row[f"{prefix}_sum_ns"] = "1000000"
        row[f"{prefix}_max_ns"] = "50000"
        for suffix, _ in telemetry.BUCKETS:
            row[f"{prefix}_{suffix}"] = "0"
        row[f"{prefix}_le_16us"] = "99"
        row[f"{prefix}_le_64us"] = "1"
    for event_class in telemetry.EVENT_CLASSES:
        count = 120 if event_class == "motion" else 0
        row[f"{event_class}_count"] = str(count)
        row[f"{event_class}_age_sum_ns"] = str(count * 10_000)
        row[f"{event_class}_age_max_ns"] = "50000" if count else "0"
        for suffix, _ in telemetry.BUCKETS:
            row[f"{event_class}_age_{suffix}"] = "0"
        row[f"{event_class}_age_le_16us"] = str(count)
    return row


class InputTelemetryAnalyzerTest(unittest.TestCase):
    def test_percentile_uses_conservative_bucket_upper_bound(self):
        distribution = {
            "count": 100,
            "histogram": [0, 0, 0, 0, 95, 4, 1] + [0] * 9,
        }
        self.assertEqual(telemetry.percentile_upper_us(distribution, 95), 16)
        self.assertEqual(telemetry.percentile_upper_us(distribution, 99), 32)
        self.assertEqual(telemetry.percentile_upper_us(distribution, 99.9), 64)

    def test_summary_aggregates_intervals(self):
        summary = telemetry.summarize([capture_row(), capture_row()])
        self.assertEqual(summary["events_processed"], 240)
        self.assertEqual(summary["events_per_second"], 120)
        self.assertEqual(summary["max_queue_depth"], 4)
        self.assertEqual(summary["sample_divisor"], 64)
        self.assertEqual(summary["distributions"]["producer_wait"]["percentile_upper_us"]["99"], 16)
        self.assertEqual(summary["event_queue_age"]["motion"]["count"], 240)

    def test_histogram_count_mismatch_is_rejected(self):
        row = capture_row()
        row["motion_age_le_16us"] = "119"
        with self.assertRaisesRegex(ValueError, "histogram count mismatch"):
            telemetry.summarize([row])

    def test_negative_values_are_rejected(self):
        row = capture_row()
        row["max_queue_depth"] = "-1"
        with self.assertRaisesRegex(ValueError, "negative value"):
            telemetry.summarize([row])

    def test_empty_event_class_formats_as_not_available(self):
        output = telemetry.format_text(telemetry.summarize([capture_row()]))
        self.assertIn("button: count=0 mean=0.000 p95=n/a p99=n/a p99.9=n/a", output)

    def test_legacy_schema_remains_readable(self):
        row = capture_row(schema_version=1)
        row.pop("motions_queued")
        summary = telemetry.summarize([row])
        self.assertEqual(summary["schema_version"], 1)
        self.assertEqual(summary["sample_divisor"], 1)


if __name__ == "__main__":
    unittest.main()
