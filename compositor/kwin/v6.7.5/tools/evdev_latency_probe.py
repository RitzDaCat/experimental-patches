#!/usr/bin/env python3
"""Measure evdev timestamp-to-reader latency without grabbing the device."""

from __future__ import annotations

import argparse
import fcntl
import os
from pathlib import Path
import platform
import select
import statistics
import struct
import time

from evdev import InputDevice, ecodes, list_devices


CLOCK_MONOTONIC = 1


def _iow(type_: int, number: int, size: int) -> int:
    # Linux asm-generic ioctl layout, used by x86_64 on this installation.
    return (1 << 30) | (size << 16) | (type_ << 8) | number


EVIOCSCLOCKID = _iow(ord("E"), 0xA0, struct.calcsize("i"))
DEFAULT_GATE_FILE = Path.home() / ".config/environment.d/90-kwin-latency.conf"


def configured_kernel_release() -> str | None:
    env_value = os.environ.get("KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE")
    if env_value:
        return env_value
    try:
        for line in DEFAULT_GATE_FILE.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE":
                return value.strip()
    except FileNotFoundError:
        pass
    return None


def find_device(path: str | None, name: str) -> InputDevice:
    if path:
        return InputDevice(path)
    matches = []
    for candidate in list_devices():
        device = InputDevice(candidate)
        if name.casefold() in device.name.casefold():
            matches.append(device)
        else:
            device.close()
    if not matches:
        raise SystemExit(f"no evdev device name contains {name!r}")
    if len(matches) > 1:
        paths = ", ".join(device.path for device in matches)
        raise SystemExit(f"multiple devices match {name!r}: {paths}; pass --device")
    return matches[0]


def percentile(sorted_values: list[int], fraction: float) -> int:
    index = min(len(sorted_values) - 1, int((len(sorted_values) - 1) * fraction))
    return sorted_values[index]


def distribution(label: str, values_ns: list[int]) -> None:
    values_ns.sort()
    values_us = [percentile(values_ns, fraction) / 1_000 for fraction in (0.5, 0.95, 0.99, 0.999)]
    print(
        f"{label}: p50={values_us[0]:.1f} us p95={values_us[1]:.1f} us "
        f"p99={values_us[2]:.1f} us p99.9={values_us[3]:.1f} us "
        f"max={values_ns[-1] / 1_000:.1f} us"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="evdev path; otherwise match --name")
    parser.add_argument("--name", default="Logitech X2 SUPERSTRIKE")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--start-delay", type=float, default=3.0)
    parser.add_argument(
        "--expected-kernel",
        default=configured_kernel_release(),
        help="exact uname -r allowed to run (defaults to the KWin experiment gate)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    running_kernel = platform.release()
    if not args.expected_kernel:
        raise SystemExit("no expected kernel configured; pass --expected-kernel explicitly")
    if running_kernel != args.expected_kernel:
        raise SystemExit(
            f"kernel gate refused probe: running={running_kernel!r}, expected={args.expected_kernel!r}"
        )
    if args.duration <= 0:
        raise SystemExit("--duration must be positive")
    if args.start_delay < 0:
        raise SystemExit("--start-delay cannot be negative")

    device = find_device(args.device, args.name)
    fcntl.ioctl(device.fd, EVIOCSCLOCKID, struct.pack("i", CLOCK_MONOTONIC))

    delays_ns: list[int] = []
    timestamps_ns: list[int] = []
    relative_events = 0
    button_events = 0
    read_wakeups = 0
    syn_dropped = 0

    print(f"kernel gate: active ({running_kernel})")
    print(f"device: {device.path} ({device.name})")
    if args.start_delay:
        print(f"starting in {args.start_delay:g} seconds")
        time.sleep(args.start_delay)
    print(f"sampling for {args.duration:g} seconds; move continuously and click a few times")

    deadline = time.monotonic() + args.duration
    while time.monotonic() < deadline:
        ready, _, _ = select.select([device.fd], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            break
        events = device.read()
        reader_timestamp_ns = time.monotonic_ns()
        read_wakeups += 1
        for event in events:
            if event.type == ecodes.EV_REL:
                relative_events += 1
            elif event.type == ecodes.EV_KEY and event.code >= ecodes.BTN_MOUSE:
                button_events += 1
            elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                syn_dropped += 1
            if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                event_timestamp_ns = event.sec * 1_000_000_000 + event.usec * 1_000
                timestamps_ns.append(event_timestamp_ns)
                delays_ns.append(max(0, reader_timestamp_ns - event_timestamp_ns))

    device.close()
    print(
        f"reports={len(timestamps_ns)} read_wakeups={read_wakeups} "
        f"relative_events={relative_events} button_events={button_events} syn_dropped={syn_dropped}"
    )
    if not timestamps_ns:
        print("no reports observed; rerun while continuously moving the mouse")
        return 2

    distribution("kernel-to-reader", delays_ns)
    gaps_ns = [later - earlier for earlier, later in zip(timestamps_ns, timestamps_ns[1:]) if later > earlier]
    if gaps_ns:
        distribution("changed-report interval", gaps_ns)
        for cutoff_us in (250, 500, 1_000, 2_000):
            active = [gap for gap in gaps_ns if gap <= cutoff_us * 1_000]
            if active:
                median_ns = statistics.median(active)
                print(
                    f"interval <= {cutoff_us:4d} us: n={len(active):6d} "
                    f"median={median_ns / 1_000:7.1f} us implied={1_000_000_000 / median_ns:7.0f} Hz"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
