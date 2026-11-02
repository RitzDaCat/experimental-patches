#!/usr/bin/env python3

import unittest

from models.adaptive_render_budget import AdaptiveRenderBudgetController


class AdaptiveRenderBudgetControllerTest(unittest.TestCase):
    def setUp(self):
        self.refresh_ns = 1_000_000_000_000 // 240_000
        self.controller = AdaptiveRenderBudgetController(self.refresh_ns)

    def warm(self, path="vsync", duration_ns=400_000):
        for _ in range(self.controller.window_size):
            self.assertTrue(self.controller.sample(path, duration_ns))

    def test_bounds_scale_from_refresh_duration(self):
        sixty = AdaptiveRenderBudgetController(1_000_000_000 // 60)
        self.assertEqual(sixty.floor_ns, sixty.refresh_ns // 64)
        self.assertEqual(sixty.guard_ns, sixty.refresh_ns // 1024)
        self.assertEqual(sixty.ceiling_ns, sixty.refresh_ns * 2)
        self.assertGreater(sixty.floor_ns, self.controller.floor_ns)

    def test_clean_warmup_uses_observed_tail_not_static_floor(self):
        self.warm(duration_ns=400_000)
        state = self.controller.states["vsync"]
        self.assertTrue(state.warmed_up)
        self.assertEqual(state.budget_ns, 400_000 + self.controller.guard_ns)

    def test_live_bootstrap_is_refresh_relative_then_first_sample_takes_over(self):
        self.assertEqual(self.controller.applied_budget("vsync", 7_000_000), self.controller.bootstrap_ns)
        self.controller.sample("vsync", 400_000)
        self.assertEqual(self.controller.applied_budget("vsync", 7_000_000), 400_000 + self.controller.guard_ns)

    def test_single_spike_is_temporary_not_persistent(self):
        self.warm()
        baseline = self.controller.states["vsync"].budget_ns
        self.controller.sample("vsync", 2_000_000)
        state = self.controller.states["vsync"]
        self.assertEqual(state.budget_ns, baseline)
        self.assertGreater(state.emergency_ns, baseline)
        for _ in range(self.controller.emergency_frames):
            self.controller.sample("vsync", 400_000)
        self.assertEqual(state.emergency_ns, 0)

    def test_repeated_tail_raises_persistent_budget_immediately(self):
        self.warm()
        self.controller.sample("vsync", 2_000_000)
        self.controller.sample("vsync", 1_900_000)
        self.assertEqual(self.controller.states["vsync"].budget_ns, 1_900_000 + self.controller.guard_ns)

    def test_clean_window_decays_by_fraction_of_excess(self):
        # Literal values on purpose. Recomputing the controller's own
        # `initial - max((initial - target) // 4, guard_ns)` here made the test
        # tautological -- changing the model's `// 4` changed the expectation
        # with it. With guard_ns = 4_069, a warm window at 2 ms settles the
        # budget at 2_004_069 ns; one clean 400 us window decays a quarter of
        # the 1_600_000 ns excess, to 1_604_069 ns.
        self.warm(duration_ns=2_000_000)
        self.assertEqual(self.controller.states["vsync"].budget_ns, 2_004_069)
        self.warm(duration_ns=400_000)
        self.assertEqual(self.controller.states["vsync"].budget_ns, 1_604_069)

    def test_paths_are_isolated(self):
        self.warm("vsync", 400_000)
        self.assertTrue(self.controller.states["vsync"].warmed_up)
        self.assertFalse(self.controller.states["adaptive-sync"].warmed_up)

    def test_zero_duration_direct_scanout_does_not_train(self):
        # A zero-duration frame reports no render work, so it must not feed the
        # max-trackers or raise the budget. It does advance the decay window --
        # see test_direct_scanout_frames_clear_a_latched_emergency_budget.
        self.warm(duration_ns=400_000)
        state = self.controller.states["vsync"]
        baseline = state.budget_ns
        self.assertFalse(self.controller.sample("vsync", 0))
        self.assertEqual(state.largest_ns, 0)
        self.assertEqual(state.second_largest_ns, 0)
        self.assertEqual(state.budget_ns, baseline)
        self.assertEqual(state.sample_count, 1)

    def test_direct_scanout_frames_clear_a_latched_emergency_budget(self):
        # Regression for the BLOCKER in docs/CODE_REVIEW_2026-08-07.md section 2.
        # queryRenderTime() reports nothing on a fully direct-scanout frame. When
        # the zero-duration guard returned before ageing the emergency budget, one
        # spike latched renderPrediction() for as long as scanout continued, so the
        # compositor woke up to two refresh intervals early on every frame.
        self.warm(duration_ns=400_000)
        self.controller.sample("vsync", 2_000_000)
        state = self.controller.states["vsync"]
        self.assertGreater(state.emergency_ns, 0)

        for _ in range(self.controller.emergency_frames):
            self.assertFalse(self.controller.sample("vsync", 0))

        self.assertEqual(state.emergency_ns, 0)
        self.assertEqual(state.emergency_frames_left, 0)

    def test_sustained_direct_scanout_still_decays_the_budget(self):
        # The same guard also froze windowSampleCount, so a budget raised by a
        # spike could never decay while the game stayed in direct scanout.
        self.warm(duration_ns=2_000_000)
        inflated = self.controller.states["vsync"].budget_ns
        for _ in range(self.controller.window_size):
            self.controller.sample("vsync", 0)
        self.assertLess(self.controller.states["vsync"].budget_ns, inflated)

    def test_shadow_mode_never_applies_learned_budget(self):
        self.warm()
        self.assertEqual(self.controller.applied_budget("vsync", 7_000_000, mode=1), 7_000_000)

    def test_refresh_reset_discards_every_path(self):
        self.warm()
        self.controller.reset()
        self.assertTrue(all(not state.warmed_up for state in self.controller.states.values()))


if __name__ == "__main__":
    unittest.main()
