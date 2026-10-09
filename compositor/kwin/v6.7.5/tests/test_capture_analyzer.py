import csv
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYZER = ROOT / "tools" / "analyze_capture.py"


class CaptureAnalyzerTest(unittest.TestCase):
    def test_revision15_flushes_each_output_by_its_own_row_count(self):
        renderloop = (
            ROOT / "reference" / "patched-overlay" / "src" / "core" / "renderloop.cpp"
        ).read_text()
        private_header = (
            ROOT / "reference" / "patched-overlay" / "src" / "core" / "renderloop_p.h"
        ).read_text()
        self.assertIn("++latencyRowsSinceFlush == 256", renderloop)
        self.assertIn("uint64_t latencyRowsSinceFlush = 0;", private_header)
        self.assertNotIn("frameTelemetry.frameSequence % 256", renderloop)

    def test_summarizes_compositor_and_drm_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            telemetry = Path(directory) / "kwin-telemetry"
            telemetry.mkdir()
            compositor = telemetry / "kwin perf statistics DP-1.csv"
            with compositor.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "vrr", "wake lateness", "raw render duration",
                    "presentation test duration", "present queue duration",
                    "direct scanout reason", "repaint decision", "presentation fallbacks",
                ])
                writer.writeheader()
                writer.writerow({"vrr": 1, "wake lateness": 2000, "raw render duration": 3000,
                                 "presentation test duration": 4000, "present queue duration": 5000,
                                 "direct scanout reason": 1, "repaint decision": 1,
                                 "presentation fallbacks": 0})
            drm = telemetry / "kwin drm timing DP-1.csv"
            with drm.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "success", "vrr", "ioctl_ns", "queue_age_ns",
                    "callback_after_submit_ns", "readiness_retries", "queue_depth",
                ])
                writer.writeheader()
                writer.writerow({"success": 1, "vrr": 1, "ioctl_ns": 6000,
                                 "queue_age_ns": 7000, "callback_after_submit_ns": 8000,
                                 "readiness_retries": 2, "queue_depth": 1})
            result = subprocess.run(
                ["python3", str(ANALYZER), str(Path(directory))],
                check=True, text=True, capture_output=True,
            )
            self.assertIn("accepted", result.stdout)
            self.assertIn("IOCTL p50/p95/p99", result.stdout)
            self.assertIn("2 / 1", result.stdout)

    def test_counts_one_wake_once_when_several_frames_share_it(self):
        """Rows are per completed frame; wake columns repeat and must not be re-counted."""
        with tempfile.TemporaryDirectory() as directory:
            telemetry = Path(directory) / "kwin-telemetry"
            telemetry.mkdir()
            compositor = telemetry / "kwin perf statistics DP-1.csv"
            with compositor.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "vrr", "wake sample sequence", "wake lateness", "raw render duration",
                    "presentation test duration", "present queue duration",
                    "direct scanout reason", "repaint decision", "presentation fallbacks",
                ])
                writer.writeheader()
                # One wake, two completed frames: the 900000 ns lateness is one event.
                writer.writerow({"vrr": 1, "wake sample sequence": 15408, "wake lateness": 900000,
                                 "raw render duration": 161601, "presentation test duration": 4000,
                                 "present queue duration": 5000, "direct scanout reason": 1,
                                 "repaint decision": 1, "presentation fallbacks": 0})
                writer.writerow({"vrr": 1, "wake sample sequence": 15408, "wake lateness": 900000,
                                 "raw render duration": 1146588, "presentation test duration": 4000,
                                 "present queue duration": 5000, "direct scanout reason": 1,
                                 "repaint decision": 1, "presentation fallbacks": 0})
                # A separate wake with a low lateness keeps the median honest.
                writer.writerow({"vrr": 1, "wake sample sequence": 15409, "wake lateness": 1000,
                                 "raw render duration": 20000, "presentation test duration": 4000,
                                 "present queue duration": 5000, "direct scanout reason": 1,
                                 "repaint decision": 1, "presentation fallbacks": 0})
            result = subprocess.run(
                ["python3", str(ANALYZER), str(Path(directory)), "--json"],
                check=True, text=True, capture_output=True,
            )
            report = json.loads(result.stdout)
            compositor_report = report["compositor"][0]
            self.assertEqual(compositor_report["sampled_frames"], 3)
            self.assertEqual(compositor_report["wake_samples"], 2)
            self.assertEqual(compositor_report["duplicate_wake_rows"], 1)
            # Two distinct wakes, so the median is their midpoint rather than 900000.
            self.assertEqual(compositor_report["wake_lateness"]["count"], 2)
            self.assertLess(compositor_report["wake_lateness"]["p50_ns"], 900000)
            # Render durations stay per frame; collapsing them would lose a real sample.
            self.assertEqual(compositor_report["raw_render_duration"]["count"], 3)
            self.assertEqual(compositor_report["raw_render_duration"]["max_ns"], 1146588)

    def test_names_specific_early_scanout_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            telemetry = Path(directory) / "kwin-telemetry"
            telemetry.mkdir()
            compositor = telemetry / "kwin perf statistics DP-1.csv"
            with compositor.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "actual wake timestamp", "direct scanout reason",
                ])
                writer.writeheader()
                writer.writerow({"actual wake timestamp": 1, "direct scanout reason": 12})
                writer.writerow({"actual wake timestamp": 2, "direct scanout reason": 13})
            result = subprocess.run(
                ["python3", str(ANALYZER), str(Path(directory))],
                check=True, text=True, capture_output=True,
            )
            self.assertIn("shadow_buffer_required", result.stdout)
            self.assertIn("color_pipeline_unsupported", result.stdout)

    def test_rejects_telemetry_that_predates_the_current_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)
            telemetry = capture / "kwin-telemetry"
            telemetry.mkdir()
            (capture / "window.txt").write_text(
                "start_epoch=1000\n"
                "start_monotonic_ns=100000000000\n"
                "end_monotonic_ns=110000000000\n"
            )
            compositor = telemetry / "kwin perf statistics DP-1.csv"
            with compositor.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "actual wake timestamp", "direct scanout reason",
                ])
                writer.writeheader()
                writer.writerow({"actual wake timestamp": 105000000000, "direct scanout reason": 13})
            os.utime(compositor, (850, 850))
            result = subprocess.run(
                ["python3", str(ANALYZER), str(capture)],
                check=True, text=True, capture_output=True,
            )
            self.assertIn("Rejected stale KWin telemetry", result.stdout)
            self.assertIn("No valid KWin telemetry", result.stdout)
            self.assertNotIn("color_pipeline_unsupported", result.stdout)

    def test_correlates_every_frame_to_exact_drm_pageflip_and_clocks(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)
            telemetry = capture / "kwin-telemetry"
            telemetry.mkdir()
            (capture / "window.txt").write_text(
                "start_epoch=1000\n"
                "start_monotonic_ns=100\n"
                "end_monotonic_ns=1000\n"
            )
            compositor = telemetry / "kwin perf statistics DP-1.csv"
            with compositor.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "actual wake timestamp", "render end", "pageflip timestamp",
                    "target pageflip timestamp", "frame sequence",
                    "frame created timestamp", "composite start timestamp",
                    "completion callback timestamp", "direct scanout reason",
                ])
                writer.writeheader()
                writer.writerow({
                    "actual wake timestamp": 0,
                    "render end": 300,
                    "pageflip timestamp": 800,
                    "target pageflip timestamp": 790,
                    "frame sequence": 1,
                    "frame created timestamp": 250,
                    "composite start timestamp": 220,
                    "completion callback timestamp": 850,
                    "direct scanout reason": 1,
                })
                writer.writerow({
                    "actual wake timestamp": 0,
                    "render end": 1100,
                    "pageflip timestamp": 1150,
                    "target pageflip timestamp": 1140,
                    "frame sequence": 3,
                    "frame created timestamp": 1050,
                    "composite start timestamp": 1020,
                    "completion callback timestamp": 1200,
                    "direct scanout reason": 1,
                })
            drm = telemetry / "kwin drm timing DP-1.csv"
            with drm.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "sequence", "queued_ns", "submit_start_ns", "submit_end_ns",
                    "pageflip_timestamp_ns", "callback_ns", "success", "queue_depth",
                ])
                writer.writeheader()
                writer.writerow({
                    "sequence": 1,
                    "queued_ns": 350,
                    "submit_start_ns": 400,
                    "submit_end_ns": 500,
                    "pageflip_timestamp_ns": 800,
                    "callback_ns": 850,
                    "success": 1,
                    "queue_depth": 1,
                })
                writer.writerow({
                    "sequence": 2,
                    "queued_ns": 1050,
                    "submit_start_ns": 1100,
                    "submit_end_ns": 1120,
                    "pageflip_timestamp_ns": 1150,
                    "callback_ns": 1200,
                    "success": 1,
                    "queue_depth": 1,
                })
            (capture / "clock-correlation.tsv").write_text(
                "label\tsequence\tpid\tmonotonic_before_ns\tmonotonic_after_ns"
                "\tbracket_ns\tmonotonic_midpoint_ns\trealtime_ns\tmonotonic_ns"
                "\tmonotonic_raw_ns\tboottime_ns\n"
                "start\t0\t1\t190\t210\t20\t200\t1200\t202\t198\t203\n"
            )
            result = subprocess.run(
                ["python3", str(ANALYZER), str(capture)],
                check=True, text=True, capture_output=True,
            )
            self.assertIn("Exact frame IDs / window flush proven: yes / yes", result.stdout)
            self.assertIn("Window selector / post-window rows: completion callback timestamp / 1", result.stdout)
            self.assertIn("Exact DRM-pageflip joins / eligible / unmatched: 1 / 1 / 0 (100.00% coverage)", result.stdout)
            self.assertIn("Frame-created-to-submit p50/p95/p99: 150 ns", result.stdout)
            self.assertIn("Read bracket p50/p95/max: 20 ns", result.stdout)

    def test_warns_when_exact_capture_tail_is_not_proven_flushed(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)
            telemetry = capture / "kwin-telemetry"
            telemetry.mkdir()
            (capture / "window.txt").write_text(
                "start_monotonic_ns=100\nend_monotonic_ns=1000\n"
            )
            compositor = telemetry / "kwin perf statistics DP-1.csv"
            with compositor.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "frame sequence", "completion callback timestamp",
                    "pageflip timestamp",
                ])
                writer.writeheader()
                writer.writerow({
                    "frame sequence": 1,
                    "completion callback timestamp": 800,
                    "pageflip timestamp": 750,
                })
            result = subprocess.run(
                ["python3", str(ANALYZER), str(capture)],
                check=True, text=True, capture_output=True,
            )
            self.assertIn("Exact frame IDs / window flush proven: yes / no", result.stdout)
            self.assertIn("buffered tail reached disk", result.stdout)
            self.assertIn("Pageflip cadence p50/p95/p99: n/a", result.stdout)

    def test_reports_unmatched_pageflip_correlation(self):
        with tempfile.TemporaryDirectory() as directory:
            capture = Path(directory)
            telemetry = capture / "kwin-telemetry"
            telemetry.mkdir()
            compositor = telemetry / "kwin perf statistics DP-1.csv"
            with compositor.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "actual wake timestamp", "pageflip timestamp",
                ])
                writer.writeheader()
                writer.writerow({
                    "actual wake timestamp": 200,
                    "pageflip timestamp": 800,
                })
            drm = telemetry / "kwin drm timing DP-1.csv"
            with drm.open("w", newline="") as output:
                writer = csv.DictWriter(output, fieldnames=[
                    "submit_start_ns", "pageflip_timestamp_ns",
                ])
                writer.writeheader()
                writer.writerow({
                    "submit_start_ns": 400,
                    "pageflip_timestamp_ns": 801,
                })
            result = subprocess.run(
                ["python3", str(ANALYZER), str(capture)],
                check=True, text=True, capture_output=True,
            )
            self.assertIn("0 / 1 / 1 (0.00% coverage)", result.stdout)
            self.assertIn("did not join to a DRM record", result.stdout)

    def test_summarizes_cold_color_wallclock_records(self):
        with tempfile.TemporaryDirectory() as directory:
            telemetry = Path(directory) / "kwin-telemetry"
            telemetry.mkdir()
            (telemetry / "kwin color pipeline.log").write_text(
                "record=1 timestamp_ns=10 duration_ns=120 intent=0 input_type=0\n"
                "source=x\nend_record\n"
            )
            (telemetry / "kwin drm color match.log").write_text(
                "record=1 timestamp_ns=20 duration_ns=80 matched=1 "
                "residual_inverse_scaling=0 compensated_non_bypassable=1\n"
                "requested_pipeline=x\nend_record\n"
            )
            result = subprocess.run(
                ["python3", str(ANALYZER), str(Path(directory))],
                check=True, text=True, capture_output=True,
            )
            self.assertIn("Color telemetry: kwin color pipeline.log", result.stdout)
            self.assertIn("Duration p50/p95/p99/max: 120 ns", result.stdout)
            self.assertIn("1 / 0 / 1", result.stdout)


if __name__ == "__main__":
    unittest.main()
