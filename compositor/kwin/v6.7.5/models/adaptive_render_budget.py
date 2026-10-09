#!/usr/bin/env python3

"""Executable model for the gated per-path KWin render-budget controller."""

from dataclasses import dataclass, field


PATHS = ("vsync", "adaptive-sync", "async", "adaptive-async")


@dataclass
class RenderBudgetState:
    budget_ns: int = 0
    emergency_ns: int = 0
    largest_ns: int = 0
    second_largest_ns: int = 0
    sample_count: int = 0
    emergency_frames_left: int = 0
    warmed_up: bool = False


@dataclass
class AdaptiveRenderBudgetController:
    refresh_ns: int
    window_size: int = 128
    states: dict[str, RenderBudgetState] = field(init=False)

    def __post_init__(self):
        if self.refresh_ns <= 0:
            raise ValueError("refresh duration must be positive")
        self.reset()

    @property
    def floor_ns(self):
        return max(self.refresh_ns // 64, 1)

    @property
    def guard_ns(self):
        return max(self.refresh_ns // 1024, 1)

    @property
    def hysteresis_ns(self):
        return max(self.refresh_ns // 256, 1)

    @property
    def ceiling_ns(self):
        return self.refresh_ns * 2

    @property
    def bootstrap_ns(self):
        return max(self.refresh_ns // 2, 1)

    @property
    def emergency_frames(self):
        return max(self.window_size // 16, 1)

    def reset(self):
        self.states = {path: RenderBudgetState() for path in PATHS}

    def _target(self, value_ns: int):
        return min(max(value_ns + self.guard_ns, self.floor_ns), self.ceiling_ns)

    def _close_window(self, state):
        target = self._target(state.second_largest_ns)
        if target > state.budget_ns:
            state.budget_ns = target
        elif target + self.hysteresis_ns <= state.budget_ns:
            difference = state.budget_ns - target
            state.budget_ns = max(target, state.budget_ns - max(difference // 4, self.guard_ns))

        state.largest_ns = 0
        state.second_largest_ns = 0
        state.sample_count = 0

    def sample(self, path: str, raw_duration_ns: int):
        if path not in self.states:
            raise ValueError(f"unknown presentation path: {path}")

        state = self.states[path]

        # A fully direct-scanout frame reports no render duration. That is a real
        # observation of near-zero compositor work, not a missing measurement. It
        # must still age the emergency budget and advance the decay window. If it
        # does not, one spike latches applied_budget() for the whole scanout run
        # and the compositor wakes up to two refresh intervals early every frame.
        if state.emergency_frames_left:
            state.emergency_frames_left -= 1
            if not state.emergency_frames_left:
                state.emergency_ns = 0

        if raw_duration_ns <= 0:
            state.sample_count += 1
            if state.sample_count >= self.window_size:
                self._close_window(state)
            return False

        bounded = min(raw_duration_ns, self.ceiling_ns)
        state.sample_count += 1
        if bounded >= state.largest_ns:
            state.second_largest_ns = state.largest_ns
            state.largest_ns = bounded
        elif bounded > state.second_largest_ns:
            state.second_largest_ns = bounded

        was_warmed_up = state.warmed_up
        if not was_warmed_up:
            state.budget_ns = self._target(bounded)
            state.warmed_up = True
        else:
            sample_target = self._target(bounded)
            if sample_target > state.budget_ns:
                state.emergency_ns = max(state.emergency_ns, sample_target)
                state.emergency_frames_left = self.emergency_frames

            repeated_target = self._target(state.second_largest_ns)
            if repeated_target > state.budget_ns:
                state.budget_ns = repeated_target

        if state.sample_count < self.window_size:
            return True

        self._close_window(state)
        return True

    def applied_budget(self, path: str, stock_prediction_ns: int, *, mode: int = 2):
        state = self.states[path]
        if mode != 2:
            return stock_prediction_ns
        if not state.warmed_up:
            return self.bootstrap_ns
        return max(state.budget_ns, state.emergency_ns)
