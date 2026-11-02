# KWin

Current target: KWin 6.8.2-1.1. The series applies with no fuzz and the
patched KWin compiles and passes its patched-path tests; no package has been
built, installed or run yet (revision 26). See the
[compatibility matrix](../../compatibility/).

The complete [KWin 6.8.2 bundle](v6.8.2/) is included here: all 18 patches,
the Arch package recipe, installer, opt-in and per-game wrappers, capture tools,
tests and source references. No private repository is needed.

Use the bundled installer and [tester guide](v6.8.2/TESTING.md). They preserve
the compositor's install checks and offline rollback path.

| Patch set | Base | In short | Status |
| --- | --- | --- | --- |
| [Interactive latency](v6.8.2/) | KWin 6.8.2 | Wake the compositor later and more precisely, so each frame carries fresher input | Wake timing measured; input-to-photon gain not shown |

## Start here

Arch-based Plasma Wayland systems only. Keep a signed stock KWin package for
offline recovery and follow the exact version checks; other versions need a port.
From this collection's root:

```bash
cd compositor/kwin/v6.8.2
./bin/kwin-latencyctl status
./bin/kwin-latencyctl test --source-only
./install.sh
```

Installation replaces KWin. Restart the desktop afterward, then verify the
kernel gate and opt-in state with `status`. The experiment defaults off;
enable it per game with `kwin-latency-game -- %command%`, or use the guide's
session-wide opt-in. Confirm the active/off state in every comparison arm.

For a working desktop, `./bin/kwin-latencyctl disable` restores stock policy;
`rollback` restores a stock package. If the desktop does not start, use a text
console and reinstall the retained signed stock package as described in the
[bundled recovery guide](v6.8.2/README.md#if-something-goes-wrong).

See [IMPORT.md](v6.8.2/IMPORT.md) for the source revision and standalone
adaptations. Source/model checks do not validate this bundle's live compositor.

## Interactive latency

What it changes: KWin decides when to start drawing the next frame. Stock
KWin 6.8.2 waits on a precise absolute `timerfd` deadline but adds a fixed
1 ms safety margin. The patched build learns the margin it actually needs for
each monitor and display path instead.

Why: A compositor that wakes too early draws the frame with older mouse
and keyboard input than it could have used. The fixed margin makes KWin wake
earlier than it needs to.

Expected result: KWin starts each frame later and closer to its deadline,
so the frame shows slightly newer input. Measured so far: the wake-up timing
itself, per monitor. Not shown: an actual input-to-photon improvement. That
needs a physical measurement (a high-speed camera or a photodiode tester),
which has not been done yet.

How to test: Follow the included
[TESTING.md](v6.8.2/TESTING.md):
install, verify, compare against stock KWin, report, and recover.

## The patches

All 18, in apply order, in the included
[`patches/`](v6.8.2/patches/).
Every experimental behaviour stays off unless the running kernel matches the
one the build was made for (patch 5), and the whole policy is off until a
tester opts in (patch 20). Numbers are stable IDs: 1 and 2 (the precise
timer) are part of KWin 6.8, 13 is obsolete in 6.8, and 15 is not ported yet.

| # | Patch | What it does |
| --- | --- | --- |
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
| 14 | `0014-fix-inverse-srgb-linear-segment` | Fixes the dark end of KWin's inverse sRGB curve |
| 16 | `0016-compensate-mandatory-color-pipeline-curves` | Cancels out NVIDIA's fixed colour stages with exact inverse curves; only with `KWIN_DRM_USE_COLOR_PIPELINE=1` |
| 17 | `0017-exact-frame-and-color-capture` | Capture links each finished frame to its DRM submit and page flip |
| 18 | `0018-guard-wake-sample-consumption` | Each wake trains the margin once, never twice |
| 19 | `0019-default-low-latency-policy` | Turned the policy on by default. Replaced by patch 20 |
| 20 | `0020-runtime-optin-latency-policy` | Policy is off by default and switched on or off live in `kwinrc` (`[LatencyExperiment]`) |
| 21 | `0021-selectable-mandatory-csc-pq-scale` | Makes the brightness scale of NVIDIA's fixed colour stages selectable (`KWIN_DRM_NVIDIA_CSC_PQ_SCALE`) |
| 22 | `0022-precisetimer-clamp-nonpositive-deadline` | A timer deadline at or before zero fires at once instead of never firing or aborting KWin |
