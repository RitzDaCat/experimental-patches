# KWin

The complete [KWin 6.7.5 bundle](v6.7.5/) is included here: all 21 patches,
the Arch package recipe, installer, opt-in and per-game wrappers, capture tools,
tests and source references. No private repository is needed.

Use the bundled installer and [tester guide](v6.7.5/TESTING.md). They preserve
the compositor's install checks and offline rollback path.

| Patch set | Base | In short | Status |
| --- | --- | --- | --- |
| [Interactive latency](v6.7.5/) | KWin 6.7.5 | Wake the compositor later and more precisely, so each frame carries fresher input | Wake timing **measured**; input-to-photon gain **not shown** |

## Start here

Arch-based Plasma Wayland systems only. Keep a signed stock KWin package for
offline recovery and follow the exact version checks; other versions need a port.
From this collection's root:

```bash
cd compositor/kwin/v6.7.5
./bin/kwin-latencyctl status
./bin/kwin-latencyctl test --source-only
./install.sh
```

Installation replaces KWin. Restart the desktop afterward, then verify the
kernel gate and opt-in state with `status`. The experiment defaults **off**;
enable it per game with `kwin-latency-game -- %command%`, or use the guide's
session-wide opt-in. Confirm the active/off state in every comparison arm.

For a working desktop, `./bin/kwin-latencyctl disable` restores stock policy;
`rollback` restores a stock package. If the desktop does not start, use a text
console and reinstall the retained signed stock package as described in the
[bundled recovery guide](v6.7.5/README.md#if-something-goes-wrong).

See [IMPORT.md](v6.7.5/IMPORT.md) for the source revision and standalone
adaptations. Source/model checks do not validate this bundle's live compositor.

## Interactive latency

**What it changes.** KWin decides when to start drawing the next frame. Stock
KWin 6.7.5 adds a fixed 1 ms safety margin and rounds the wait down to whole
milliseconds. The patched build waits on a precise absolute `timerfd` deadline
instead, and learns the margin it actually needs for each monitor and display
path.

**Why.** A compositor that wakes too early draws the frame with older mouse
and keyboard input than it could have used. The fixed margin and the rounding
both make KWin wake earlier than it needs to.

**Expected result.** KWin starts each frame later and closer to its deadline,
so the frame shows slightly newer input. Measured so far: the wake-up timing
itself, per monitor. **Not shown:** an actual input-to-photon improvement. That
needs a physical measurement (a high-speed camera or a photodiode tester),
which has not been done yet.

**How to test.** Follow the included
[TESTING.md](v6.7.5/TESTING.md):
install, verify, compare against stock KWin, report, and recover.

## The patches

All 21, in apply order, in the included
[`patches/`](v6.7.5/patches/).
Every experimental behaviour stays off unless the running kernel matches the
one the build was made for (patch 5), and the whole policy is off until a
tester opts in (patch 20).

| # | Patch | What it does |
| --- | --- | --- |
| 1 | `0001-precise-timer` | Backport from upstream KWin: a timer that fires at an exact absolute time |
| 2 | `0002-renderloop-timerfd` | Backport from upstream KWin: the compositor wakes on a `timerfd` instead of a whole-millisecond timer |
| 3 | `0003-wakeup-instrumentation` | Records when each wake was wanted, set and actually happened, per monitor |
| 4 | `0004-adaptive-wakeup-margin` | Learns how early the compositor needs to wake, within fixed limits, instead of a fixed 1 ms |
| 5 | `0005-kernel-release-gate` | Turns every experimental behaviour off unless the running kernel is exactly the one it was built for |
| 6 | `0006-adaptive-margin-v2` | Learns the margin separately for VSync, adaptive sync and async; a repeated stall restores the safe margin at once |
| 7 | `0007-backends-libinput-add-gated-input-queue-telemetry` | Optional input-queue timing log; off by default |
| 8 | `0008-telemetry-sample-observers-outside-nanosecond-hot-paths` | Logs only a sample of frames, so logging costs less on the hot path |
| 9 | `0009-adaptive-render-budget` | Learns how long rendering takes on each path and budgets for that, scaled to the refresh rate |
| 10 | `0010-vrr-cadence-repaint-coalescing` | With VRR, paces background repaints to the game's frame rate instead of a fixed 30 Hz fallback |
| 11 | `0011-bounded-latency-capture` | Off-by-default capture of wake, render, DRM commit and page-flip timing for a set time |
| 12 | `0012-reason-coded-capture` | Capture also records why direct scanout was refused |
| 13 | `0013-exact-kernel-nvidia-color-pipeline` | Allows NVIDIA DRM colour pipelines only on the gated kernel and driver 610.43.03 or newer |
| 14 | `0014-fix-inverse-srgb-linear-segment` | Fixes the dark end of KWin's inverse sRGB curve |
| 15 | `0015-bounded-color-hot-path-cache` | Reuses colour work that does not change between frames instead of rebuilding it |
| 16 | `0016-compensate-mandatory-color-pipeline-curves` | Cancels out NVIDIA's fixed colour stages with exact inverse curves |
| 17 | `0017-exact-frame-and-color-capture` | Capture links each finished frame to its DRM submit and page flip |
| 18 | `0018-guard-wake-sample-consumption` | Each wake trains the margin once, never twice |
| 19 | `0019-default-low-latency-policy` | Turned the policy on by default; NVIDIA colour pipelines became opt-in. Replaced by patch 20 |
| 20 | `0020-runtime-optin-latency-policy` | Policy is off by default and switched on or off live in `kwinrc` (`[LatencyExperiment]`) |
| 21 | `0021-selectable-mandatory-csc-pq-scale` | Makes the brightness scale of NVIDIA's fixed colour stages selectable (`KWIN_DRM_NVIDIA_CSC_PQ_SCALE`) |
