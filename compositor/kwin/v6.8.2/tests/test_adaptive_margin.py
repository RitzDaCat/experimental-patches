#!/usr/bin/env python3

import unittest

from models.adaptive_margin import AdaptiveMarginController


class AdaptiveMarginControllerTest(unittest.TestCase):
    def setUp(self):
        self.controller = AdaptiveMarginController()

    def feed_window(self, path="vsync", values=None):
        values = values or [10_000] * self.controller.window_size
        for value in values:
            self.assertTrue(self.controller.sample(path, value))

    # These assert literal nanosecond values on purpose. Recomputing the
    # controller's own `margin_ns - max(difference_ns // 4, guard_ns)` here made
    # the tests tautological: changing `// 4` to `// 2` in the model changed the
    # expectation with it and the suite stayed green, so the decay rate -- the
    # exact regression these guard -- was unguarded. At 240 Hz the defaults are
    # ceiling 1_041_666 ns, floor 16_276 ns, guard 2_034 ns, so one clean window
    # decays by (1_041_666 - 16_276) // 4 = 256_347 ns to 785_319 ns.
    ONE_CLEAN_WINDOW_MARGIN_NS = 785_319

    def test_clean_windows_reduce_only_one_bounded_step(self):
        self.assertEqual(self.controller.ceiling_ns, 1_041_666)
        self.feed_window()
        state = self.controller.states["vsync"]
        self.assertTrue(state.warmed_up)
        self.assertEqual(state.margin_ns, self.ONE_CLEAN_WINDOW_MARGIN_NS)

    def test_one_large_stall_does_not_poison_window(self):
        # A single 6.9 ms outlier must not change the outcome: the controller
        # tracks the second largest sample, so the window still decays exactly
        # as if every sample had been clean.
        self.feed_window(values=[6_900_000] + [10_000] * 255)
        self.assertEqual(
            self.controller.states["vsync"].margin_ns, self.ONE_CLEAN_WINDOW_MARGIN_NS
        )

    def test_two_large_stalls_restore_ceiling_immediately(self):
        self.feed_window()
        state = self.controller.states["vsync"]
        reduced = state.margin_ns
        self.controller.sample("vsync", 2_500_000)
        self.assertEqual(state.margin_ns, reduced)
        self.controller.sample("vsync", 2_500_000)
        self.assertEqual(state.margin_ns, self.controller.ceiling_ns)

    def test_second_largest_rejects_one_in_window_spike(self):
        for _ in range(32):
            self.feed_window()
        state = self.controller.states["vsync"]
        self.assertLessEqual(state.margin_ns, self.controller.floor_ns + self.controller.hysteresis_ns)
        baseline = state.margin_ns
        self.feed_window(values=[500_000] + [10_000] * 255)
        self.assertEqual(state.margin_ns, baseline)

    def test_repeated_tail_is_learned(self):
        for _ in range(32):
            self.feed_window()
        baseline = self.controller.states["vsync"].margin_ns
        self.controller.sample("vsync", 400_000)
        self.assertEqual(self.controller.states["vsync"].margin_ns, baseline)
        self.controller.sample("vsync", 400_000)
        self.assertEqual(self.controller.states["vsync"].margin_ns, 400_000 + self.controller.guard_ns)

    def test_presentation_paths_are_independent(self):
        self.feed_window("vsync")
        self.assertLess(self.controller.states["vsync"].margin_ns, self.controller.ceiling_ns)
        self.assertEqual(self.controller.states["adaptive-sync"].margin_ns, self.controller.ceiling_ns)

    def test_refresh_reset_restores_all_paths(self):
        self.feed_window("vsync")
        self.controller.reset()
        self.assertTrue(all(state.margin_ns == self.controller.ceiling_ns for state in self.controller.states.values()))
        self.assertTrue(all(not state.warmed_up for state in self.controller.states.values()))

    def test_policy_scales_with_each_output_refresh(self):
        sixty = AdaptiveMarginController(1_000_000_000 // 60)
        self.assertEqual(sixty.floor_ns, sixty.refresh_ns // 256)
        self.assertEqual(sixty.ceiling_ns, sixty.refresh_ns // 4)
        self.assertGreater(sixty.ceiling_ns, self.controller.ceiling_ns)

    def test_ineligible_samples_do_not_train(self):
        for _ in range(256):
            self.assertFalse(self.controller.sample("vsync", 10_000, eligible=False))
        self.assertEqual(self.controller.states["vsync"].sample_count, 0)


if __name__ == "__main__":
    unittest.main()
