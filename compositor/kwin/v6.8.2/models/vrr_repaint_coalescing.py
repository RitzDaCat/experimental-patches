"""Reference model for the gated VRR repaint coalescing policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


NS_PER_SECOND = 1_000_000_000
# renderloop.cpp:250 is `constexpr std::chrono::milliseconds stockDelay = 1'000ms / 30`.
# That is integer *millisecond* division, so the stock fallback delay is 33 ms
# exactly, not 1e9/30 = 33.333 ms. Modelling it as 33,333,333 ns overstated the
# stock baseline by 333 us and therefore overstated what coalescing improves on.
STOCK_DELAY_NS = (1_000 // 30) * 1_000_000
# renderloop.cpp:721 uses the nanosecond form, so this one is 1e9/30 and correct.
ACTIVE_CADENCE_LIMIT_NS = NS_PER_SECOND // 30


class RepaintAction(Enum):
    IMMEDIATE = "immediate"
    COALESCE = "coalesce"
    STOCK_DELAY = "stock-delay"


@dataclass(frozen=True)
class RepaintDecision:
    action: RepaintAction
    delay_ns: int = 0


def frame_interval_ns(rate_hz: float) -> int:
    if rate_hz <= 0:
        raise ValueError("rate_hz must be positive")
    return round(NS_PER_SECOND / rate_hz)


def decide_repaint(
    *,
    exact_kernel_gate: bool,
    coalescing_enabled: bool,
    vrr_or_tearing: bool,
    foreground_damage: bool,
    active_frame_interval_ns: int | None,
    output_refresh_interval_ns: int,
    elapsed_since_presentation_ns: int = 0,
) -> RepaintDecision:
    """Mirror the source policy without clocks, timers, or side effects."""
    if foreground_damage or not vrr_or_tearing:
        return RepaintDecision(RepaintAction.IMMEDIATE)
    if active_frame_interval_ns is None or active_frame_interval_ns > ACTIVE_CADENCE_LIMIT_NS:
        return RepaintDecision(RepaintAction.IMMEDIATE)
    if not exact_kernel_gate or not coalescing_enabled:
        return RepaintDecision(RepaintAction.STOCK_DELAY, STOCK_DELAY_NS)
    cadence_ns = max(active_frame_interval_ns, output_refresh_interval_ns)
    return RepaintDecision(
        RepaintAction.COALESCE,
        max(cadence_ns - elapsed_since_presentation_ns, 0),
    )
