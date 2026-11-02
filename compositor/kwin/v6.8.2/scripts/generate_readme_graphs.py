#!/usr/bin/env python3

"""Generate deterministic, theme-aware SVG charts used by the GitHub README."""

import argparse
import html
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models.adaptive_margin import AdaptiveMarginController  # noqa: E402
from models.vrr_repaint_coalescing import STOCK_DELAY_NS, frame_interval_ns  # noqa: E402


ASSETS = ROOT / "docs" / "assets"
METRICS = ROOT / "docs" / "data" / "readme-metrics.json"


STYLE = """
    .bg { fill: #ffffff; }
    .text { fill: #1f2328; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    .muted { fill: #59636e; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    .grid { stroke: #d0d7de; stroke-width: 1; }
    .axis { stroke: #8c959f; stroke-width: 1.5; }
    .baseline { fill: #8c959f; }
    .adaptive { fill: #0969da; }
    .adaptive-line { fill: none; stroke: #0969da; stroke-width: 3; }
    .stock-line { fill: none; stroke: #8c959f; stroke-width: 3; stroke-dasharray: 8 6; }
    .timer { fill: #8250df; }
    .event { stroke: #cf222e; stroke-width: 2; }
    .frame { fill: #8c959f; opacity: 0.45; }
    @media (prefers-color-scheme: dark) {
      .bg { fill: #0d1117; }
      .text { fill: #f0f6fc; }
      .muted { fill: #9da7b3; }
      .grid { stroke: #30363d; }
      .axis { stroke: #6e7681; }
      .baseline { fill: #6e7681; }
      .adaptive { fill: #58a6ff; }
      .adaptive-line { stroke: #58a6ff; }
      .stock-line { stroke: #9da7b3; }
      .timer { fill: #a371f7; }
      .event { stroke: #ff7b72; }
      .frame { fill: #6e7681; opacity: 0.55; }
    }
"""


def svg_open(width, height, title, description):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        f"<title id=\"title\">{html.escape(title)}</title>",
        f"<desc id=\"desc\">{html.escape(description)}</desc>",
        f"<style>{STYLE}</style>",
        f'<rect class="bg" width="{width}" height="{height}"/>',
    ]


def text_node(x, y, value, css="text", size=14, anchor="start", weight=400):
    return f'<text class="{css}" x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}">{html.escape(str(value))}</text>'


def reserve_replay(metrics):
    width, height = 960, 410
    left, right, top, bottom = 230, 70, 125, 340
    plot_width = width - left - right
    maximum = metrics["fixed_margin_us"]
    rows = [
        ("Fixed KWin reserve", maximum, "baseline", "baseline"),
        ("Primary trace replay", metrics["primary_replay_margin_us"], "adaptive", "replay"),
        ("Secondary trace replay", metrics["secondary_replay_margin_us"], "adaptive", "replay"),
    ]
    out = svg_open(
        width,
        height,
        "Fixed compositor reserve versus offline adaptive replay",
        "The fixed reserve is 1000 microseconds. Offline replay settles at 160 microseconds for the primary trace and 231 microseconds for the secondary trace.",
    )
    out += [
        text_node(40, 42, "Compositor wake reserve", size=24, weight=500),
        text_node(40, 70, "Fixed baseline compared with preliminary offline v2 replay", css="muted", size=15),
        text_node(40, 94, "Legacy capture schema; illustrative controller output, not a live latency benchmark", css="muted", size=13),
    ]
    for tick in range(0, maximum + 1, 250):
        x = left + plot_width * tick / maximum
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 12}" x2="{x:.1f}" y2="{bottom}"/>')
        out.append(text_node(x, bottom + 26, tick, css="muted", size=12, anchor="middle"))
    out.append(text_node(left + plot_width / 2, bottom + 52, "Wake reserve (microseconds)", css="muted", size=13, anchor="middle"))
    for index, (label, value, css, kind) in enumerate(rows):
        y = top + index * 68
        bar_width = plot_width * value / maximum
        out.append(text_node(left - 18, y + 25, label, size=14, anchor="end", weight=500 if kind == "baseline" else 400))
        out.append(f'<rect class="{css}" x="{left}" y="{y}" width="{bar_width:.1f}" height="36" rx="4"/>')
        out.append(text_node(left + bar_width + 12, y + 24, f"{value} us", size=14, weight=500))
        if kind == "replay":
            saved = maximum - value
            out.append(text_node(left + bar_width + 12, y + 43, f"{saved} us less reserve", css="muted", size=12))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def controller_response():
    controller = AdaptiveMarginController()
    state = controller.states["vsync"]
    sample = 0
    changes = [(sample, state.margin_ns / 1000)]

    def feed(value, count=1):
        nonlocal sample
        for _ in range(count):
            previous = state.margin_ns
            controller.sample("vsync", value)
            sample += 1
            if state.margin_ns != previous:
                changes.append((sample, previous / 1000))
                changes.append((sample, state.margin_ns / 1000))

    feed(10_000, 18 * 256)
    single_spike = sample + 1
    feed(500_000)
    feed(10_000, 255)
    repeated_tail = sample + 2
    feed(400_000, 2)
    feed(10_000, 8 * 256)
    changes.append((sample, state.margin_ns / 1000))

    width, height = 960, 430
    left, right, top, bottom = 92, 55, 105, 345
    plot_width, plot_height = width - left - right, bottom - top
    maximum_sample, maximum_margin = sample, 1100

    def px_x(value):
        return left + plot_width * value / maximum_sample

    def px_y(value):
        return bottom - plot_height * value / maximum_margin

    out = svg_open(
        width,
        height,
        "Synthetic adaptive controller response",
        "At 240 hertz, the refresh-relative reserve removes one quarter of excess after each clean 256-sample window, ignores one isolated 500 microsecond spike, and rises just above 400 microseconds after a repeated tail.",
    )
    out += [
        text_node(40, 42, "Adaptive controller response", size=24, weight=500),
        text_node(40, 70, "Deterministic reference-model scenario", css="muted", size=15),
    ]
    for margin in [0, 250, 500, 750, 1000]:
        y = px_y(margin)
        out.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>')
        out.append(text_node(left - 14, y + 4, margin, css="muted", size=12, anchor="end"))
    for position in range(0, maximum_sample + 1, 1024):
        x = px_x(position)
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}"/>')
        out.append(text_node(x, bottom + 24, position, css="muted", size=12, anchor="middle"))
    path = " ".join(("M" if index == 0 else "L") + f" {px_x(x):.1f} {px_y(y):.1f}" for index, (x, y) in enumerate(changes))
    out.append(f'<path class="adaptive-line" d="{path}"/>')
    for event_sample, label, label_y in [
        (single_spike, "One 500 us spike ignored", 135),
        (repeated_tail, "Second 400 us tail raises reserve", 175),
    ]:
        x = px_x(event_sample)
        out.append(f'<line class="event" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}"/>')
        out.append(text_node(x + 8, label_y, label, size=13, weight=500))
    out.append(
        f'<text class="muted" x="25" y="{(top + bottom) / 2:.1f}" font-size="13" '
        f'text-anchor="middle" transform="rotate(-90 25 {(top + bottom) / 2:.1f})">Reserve (us)</text>'
    )
    out.append(text_node(left + plot_width / 2, bottom + 56, "Valid timer wake samples", css="muted", size=13, anchor="middle"))
    out.append(text_node(left + 8, top + 22, "Refresh-relative proportional descent per clean window", css="muted", size=12))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def scheduling_opportunity(metrics):
    width, height = 960, 400
    left, right, top, bottom = 230, 70, 120, 320
    plot_width = width - left - right
    maximum = metrics["display_240hz_interval_us"]
    timer = metrics["timer_quantization_mean_us"]
    adaptive = metrics["fixed_margin_us"] - metrics["primary_replay_margin_us"]
    combined = timer + adaptive
    rows = [
        ("Estimated scheduling opportunity", combined, "stacked"),
        ("480 FPS render interval", metrics["game_480fps_interval_us"], "frame"),
        ("240 Hz display interval", metrics["display_240hz_interval_us"], "frame"),
    ]
    out = svg_open(
        width,
        height,
        "Estimated scheduling opportunity relative to frame intervals",
        "The estimated 1340 microsecond scheduling opportunity combines a theoretical 500 microsecond timer quantization mean and an 840 microsecond offline adaptive replay reduction. It is shown against 2083 and 4167 microsecond frame intervals.",
    )
    out += [
        text_node(40, 42, "Scheduling opportunity and frame intervals", size=24, weight=500),
        text_node(40, 70, "Estimate versus 480 FPS render and 240 Hz display cadence", css="muted", size=15),
        text_node(40, 94, "Opportunity is not an input-to-photon benchmark", css="muted", size=13),
    ]
    for tick in [0, 1000, 2000, 3000, 4000]:
        x = left + plot_width * tick / maximum
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 10}" x2="{x:.1f}" y2="{bottom}"/>')
        out.append(text_node(x, bottom + 24, tick, css="muted", size=12, anchor="middle"))
    for index, (label, value, kind) in enumerate(rows):
        y = top + index * 64
        out.append(text_node(left - 18, y + 23, label, size=14, anchor="end"))
        if kind == "stacked":
            timer_width = plot_width * timer / maximum
            adaptive_width = plot_width * adaptive / maximum
            out.append(f'<rect class="timer" x="{left}" y="{y}" width="{timer_width:.1f}" height="34" rx="4"/>')
            out.append(f'<rect class="adaptive" x="{left + timer_width:.1f}" y="{y}" width="{adaptive_width:.1f}" height="34" rx="4"/>')
            out.append(text_node(left + timer_width / 2, y + 22, "500", size=12, anchor="middle", weight=500))
            out.append(text_node(left + timer_width + adaptive_width / 2, y + 22, "840", size=12, anchor="middle", weight=500))
        else:
            out.append(f'<rect class="frame" x="{left}" y="{y}" width="{plot_width * value / maximum:.1f}" height="34" rx="4"/>')
        out.append(text_node(left + plot_width * value / maximum + 10, y + 22, f"{value / 1000:.2f} ms", size=13, weight=500))
    out.append(text_node(left + plot_width / 2, bottom + 50, "Time (microseconds)", css="muted", size=13, anchor="middle"))
    out.append(text_node(left + 8, top - 18, "timer mean", css="muted", size=11))
    out.append(text_node(left + plot_width * timer / maximum + 8, top - 18, "adaptive replay", css="muted", size=11))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def vrr_fallback_ceiling():
    rates = [30, 60, 120, 144, 240, 360, 480]
    output_interval_ms = frame_interval_ns(240) / 1_000_000
    # Not frame_interval_ns(30). Stock KWin's fallback is
    # `constexpr std::chrono::milliseconds stockDelay = 1'000ms / 30` --
    # integer millisecond division, so 33.00 ms, not 1e9/30 = 33.33 ms.
    # Plotting 33.33 overstated the stock baseline this patch improves on.
    stock_ms = STOCK_DELAY_NS / 1_000_000
    candidate = [max(frame_interval_ns(rate) / 1_000_000, output_interval_ms) for rate in rates]

    width, height = 960, 430
    left, right, top, bottom = 88, 55, 105, 340
    plot_width, plot_height = width - left - right, bottom - top
    maximum_ms = 35

    def px_x(index):
        return left + plot_width * index / (len(rates) - 1)

    def px_y(value):
        return bottom - plot_height * value / maximum_ms

    out = svg_open(
        width,
        height,
        "Stock versus cadence-derived VRR repaint fallback ceiling",
        "Stock KWin uses a 33.33 millisecond fallback. On a 240 hertz output, the candidate ceiling follows measured foreground cadence down to the 4.17 millisecond physical output interval. Foreground game damage remains immediate in both designs.",
    )
    out += [
        text_node(40, 42, "VRR unrelated-damage fallback ceiling", size=24, weight=500),
        text_node(40, 70, "240 Hz output; actual foreground damage is immediate in both designs", css="muted", size=15),
    ]
    for value in [0, 5, 10, 15, 20, 25, 30, 35]:
        y = px_y(value)
        out.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>')
        out.append(text_node(left - 12, y + 4, value, css="muted", size=12, anchor="end"))
    for index, rate in enumerate(rates):
        x = px_x(index)
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}"/>')
        out.append(text_node(x, bottom + 25, rate, css="muted", size=12, anchor="middle"))

    stock_path = " ".join(("M" if index == 0 else "L") + f" {px_x(index):.1f} {px_y(stock_ms):.1f}" for index in range(len(rates)))
    candidate_path = " ".join(("M" if index == 0 else "L") + f" {px_x(index):.1f} {px_y(value):.1f}" for index, value in enumerate(candidate))
    out.append(f'<path class="stock-line" d="{stock_path}"/>')
    out.append(f'<path class="adaptive-line" d="{candidate_path}"/>')
    for index, value in enumerate(candidate):
        out.append(f'<circle class="adaptive" cx="{px_x(index):.1f}" cy="{px_y(value):.1f}" r="4"/>')
    out += [
        text_node(width - right - 5, px_y(stock_ms) - 10, f"Stock: {stock_ms:.2f} ms", css="muted", size=13, anchor="end", weight=500),
        text_node(width - right - 5, px_y(candidate[-1]) - 10, "Candidate: 4.17 ms floor", size=13, anchor="end", weight=500),
        text_node(left + plot_width / 2, bottom + 58, "Measured active-surface cadence (FPS)", css="muted", size=13, anchor="middle"),
        f'<text class="muted" x="25" y="{(top + bottom) / 2:.1f}" font-size="13" text-anchor="middle" transform="rotate(-90 25 {(top + bottom) / 2:.1f})">Fallback ceiling (ms)</text>',
        text_node(40, height - 18, "Continuous game damage normally cancels either fallback before it expires; this targets stalls and transition tails.", css="muted", size=12),
    ]
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write_or_check(path, content, check):
    if check:
        if not path.exists() or path.read_text() != content:
            raise SystemExit(f"generated graph is stale: {path.relative_to(ROOT)}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if committed SVGs are stale")
    args = parser.parse_args()
    metrics = json.loads(METRICS.read_text())
    outputs = {
        ASSETS / "reserve-replay.svg": reserve_replay(metrics),
        ASSETS / "controller-response.svg": controller_response(),
        ASSETS / "scheduling-opportunity.svg": scheduling_opportunity(metrics),
        ASSETS / "vrr-fallback-ceiling.svg": vrr_fallback_ceiling(),
    }
    for path, content in outputs.items():
        write_or_check(path, content, args.check)


if __name__ == "__main__":
    main()
