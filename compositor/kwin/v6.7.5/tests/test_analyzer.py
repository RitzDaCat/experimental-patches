#!/usr/bin/env python3

import unittest

from tools.analyze_wakeup_csv import telemetry_sample_divisor, unique_trained_wake_samples


class AnalyzerTest(unittest.TestCase):
    def test_dispatch_sequence_is_deduplicated(self):
        rows = [
            {"wake sample valid": 1, "wake sample trained": 1, "wake sample sequence": 10},
            {"wake sample valid": 1, "wake sample trained": 1, "wake sample sequence": 10},
            {"wake sample valid": 1, "wake sample trained": 1, "wake sample sequence": 11},
            {"wake sample valid": 0, "wake sample trained": 0, "wake sample sequence": 12},
        ]
        samples = unique_trained_wake_samples(rows)
        self.assertEqual([sample["wake sample sequence"] for sample in samples], [10, 11])

    def test_sample_divisor_defaults_to_full_rate_for_legacy_capture(self):
        self.assertEqual(telemetry_sample_divisor([{"wake sample sequence": 1}]), 1)

    def test_sample_divisor_is_reported(self):
        rows = [{"telemetry sample divisor": 16}, {"telemetry sample divisor": 16}]
        self.assertEqual(telemetry_sample_divisor(rows), 16)


if __name__ == "__main__":
    unittest.main()
