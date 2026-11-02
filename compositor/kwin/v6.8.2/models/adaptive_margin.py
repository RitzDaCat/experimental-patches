#!/usr/bin/env python3

"""Executable reference model for the KWin adaptive wake-margin controller."""

from dataclasses import dataclass, field


PATHS = ("vsync", "adaptive-sync", "async", "adaptive-async")


@dataclass
class MarginState:
    margin_ns: int
    largest_ns: int = 0
    second_largest_ns: int = 0
    sample_count: int = 0
    external_stalls: int = 0
    warmed_up: bool = False


@dataclass
class AdaptiveMarginController:
    refresh_ns: int = 1_000_000_000_000 // 240_000
    window_size: int = 256
    external_stall_fallback_count: int = 2
    states: dict[str, MarginState] = field(init=False)

    def __post_init__(self):
        if self.refresh_ns <= 0:
            raise ValueError("refresh duration must be positive")
        self.reset()

    @property
    def floor_ns(self):
        return max(self.refresh_ns // 256, 1)

    @property
    def guard_ns(self):
        return max(self.refresh_ns // 2048, 1)

    @property
    def hysteresis_ns(self):
        return max(self.refresh_ns // 1024, 1)

    @property
    def ceiling_ns(self):
        return max(self.refresh_ns // 4, 1)

    def reset(self):
        self.states = {path: MarginState(self.ceiling_ns) for path in PATHS}

    def sample(self, path: str, lateness_ns: int, *, eligible: bool = True):
        if path not in self.states:
            raise ValueError(f"unknown presentation path: {path}")
        if not eligible or lateness_ns < 0:
            return False

        state = self.states[path]
        state.sample_count += 1

        if lateness_ns > self.ceiling_ns:
            state.external_stalls += 1
            if state.external_stalls >= self.external_stall_fallback_count:
                state.margin_ns = self.ceiling_ns
        elif lateness_ns >= state.largest_ns:
            state.second_largest_ns = state.largest_ns
            state.largest_ns = lateness_ns
        elif lateness_ns > state.second_largest_ns:
            state.second_largest_ns = lateness_ns

        repeated_tail_ns = min(max(state.second_largest_ns + self.guard_ns, self.floor_ns), self.ceiling_ns)
        if repeated_tail_ns > state.margin_ns:
            state.margin_ns = repeated_tail_ns

        if state.sample_count < self.window_size:
            return True

        if state.external_stalls >= self.external_stall_fallback_count:
            target_ns = self.ceiling_ns
        else:
            target_ns = min(max(state.second_largest_ns + self.guard_ns, self.floor_ns), self.ceiling_ns)

        if target_ns > state.margin_ns:
            state.margin_ns = target_ns
        elif target_ns + self.hysteresis_ns <= state.margin_ns:
            difference_ns = state.margin_ns - target_ns
            state.margin_ns = max(target_ns, state.margin_ns - max(difference_ns // 4, self.guard_ns))

        state.warmed_up = True
        state.largest_ns = 0
        state.second_largest_ns = 0
        state.sample_count = 0
        state.external_stalls = 0
        return True
