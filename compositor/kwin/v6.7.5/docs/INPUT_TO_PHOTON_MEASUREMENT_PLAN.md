# Input-to-photon measurement plan

Date: 2026-08-08

Purpose: give the project a pass mark. The stated goal is Linux esports latency
competing with Windows. That claim needs one number measured the same way on
both systems.

## 1. The gap today

The repository measures KWin-internal stages well and says so plainly:

- `docs/INPUT_LATENCY_TELEMETRY.md`, lines 111-115: the capture identifies KWin
  queue contention and queue residence time. It cannot measure USB interrupt
  latency, evdev-to-libinput translation, application input sampling, game
  simulation, render queues, scanout, or display response.
- `docs/EVDEV_INPUT_LATENCY_PROBE.md`, lines 26-27: the evdev probe measures
  kernel event timestamp to diagnostic reader only.

No input-to-photon comparison against a Windows baseline exists in `docs/`
(checked by listing `docs/` and reading both files above).

Every current patch is therefore justified by a stage number, not by the number
the goal is written in.

## 2. What input-to-photon means here

Define it as: kernel evdev timestamp of a button press, to the first photon of
the frame that reflects that press.

Break it into four segments:

| Segment | Owner | Measurable today |
| --- | --- | --- |
| Sensor and USB transport | mouse, USB host | no (needs hardware rig) |
| evdev to KWin to client | kernel, KWin | yes (patches 0007, 0008) |
| Game simulation and render | Proton, game, GPU | partly (frame telemetry) |
| Scanout and panel response | DRM, monitor | no (needs hardware rig) |

## 3. Tier 1 — in-band software proxy

Available on this machine now. `wayland-info` reports:

```text
interface: 'wp_presentation', version: 2, name: 47
	presentation clock id: 1 (CLOCK_MONOTONIC)
```

`wp_presentation` reports the time a frame was actually presented, in
`CLOCK_MONOTONIC`. The evdev probe already timestamps input in the same clock
(`docs/EVDEV_INPUT_LATENCY_PROBE.md`, line 25). The two are directly
subtractable with no clock conversion.

Build a minimal Wayland client that:

1. Reads its own evdev device with `CLOCK_MONOTONIC` timestamps.
2. Paints a full-screen color flip on the first frame after a button press.
3. Records the `wp_presentation` `presented` timestamp for that frame.
4. Writes `press_timestamp`, `presented_timestamp`, and the delta to CSV.

This yields **input-to-presented**. It covers the whole chain except sensor,
USB transport, and panel response. It is repeatable, needs no hardware, and can
A/B any compositor patch in this series directly.

Note the client is not the game. It removes game simulation from the
measurement, which makes it a clean compositor benchmark and a poor whole-stack
number. Both are useful; do not conflate them.

## 4. Tier 2 — hardware ground truth

Required for a real Windows comparison, because the missing segments differ
between operating systems.

Minimum viable rig:

1. A microcontroller that shorts the mouse button contacts and timestamps the
   moment it does.
2. A photodiode taped to the monitor over the region that changes.
3. The same microcontroller timestamps the photodiode transition.
4. Delta between the two is true input-to-photon.

This measures the identical physical path on Linux and Windows. Nothing in the
operating system can bias it.

Open-hardware latency testers of this design exist. Verify the current name,
availability, and clock resolution of any specific tool before adopting it —
do not cite one from memory.

## 5. The Windows baseline

A published Windows latency figure is not a valid baseline. Comparability
requires the same monitor, same GPU, same driver generation, same game, same
in-game settings, same refresh rate, same VRR state, and the same rig from
section 4.

Procedure:

1. Boot Windows on this machine, or on identical hardware.
2. Run the section-4 rig on one chosen esports title at fixed settings.
3. Collect at least 100 press-to-photon samples.
4. Repeat on Linux with identical settings.
5. Compare median, p95, and p99. p99 matters most for esports feel.

## 5a. Plot the phase, not just the median

Added 2026-08-08 from the second research sweep.

Do not reduce the samples to a median. Issue each keypress at a **uniformly
random phase** within the frame interval, then plot press phase on one axis
against measured photon time on the other.

A compositor that loses a whole frame under some condition shows up as a visible
step or a second band in that scatter. A median hides it completely.

Ivan Molodetskikh (author of niri, contributor to sway, wlroots, and Smithay)
reported using exactly this plot to find a one-frame loss in GNOME Shell and a
separate defect in sway, with a Teensy issuing the keypress and a light sensor
on the monitor reading the photon. The same failure class appears independently
in GNOME mutter issues 1208 and 1255, both describing input latency of up to a
single refresh cycle.

Confidence note: no public repository, dataset, or write-up for that rig was
found by a search of the author's 131 GitHub repositories and his blog index.
Treat the technique as sound and the specific defect reports as anecdote-grade.
The rig is external hardware, so it is compositor-agnostic and transfers to KWin
without a software probe.

## 5b. Two measurement warnings that outrank any optimization

- Sampling profilers miss the key events, instrumentation profilers are too
  intrusive, and microbenchmarks are not representative. Carl Cook, *When a
  Microsecond Is an Eternity*, CppCon 2017, slide 51. His recommendation is
  end-to-end measurement in a production-like setup with hardware timestamping.
- Memory-layout bias alone moves suite-average results by about 7%, and running
  more benchmarks does not cancel it. Mytkowicz et al., ASPLOS 2009.

Consequence for this project: any KWin change claiming a sub-10% effect is
unfalsifiable without end-to-end hardware timestamping and layout
randomization. That applies to several patches in this series.

## 6. Pass mark

State the target as a distribution, not an average:

> Linux median input-to-photon is within `X` ms of Windows, and Linux p99 does
> not exceed Windows p99.

Fill `X` only after the first paired measurement exists. Choosing a target
before the baseline is guesswork.

## 7. Order of work

1. Build the Tier 1 client. It is cheap and immediately A/B-tests the existing
   18 patches against each other.
2. Use Tier 1 to rank the patches by measured input-to-presented effect.
3. Build the Tier 2 rig only when a patch set is worth defending publicly.
4. Take the Windows baseline last, once the Linux side is stable.

## 8. What this plan does not solve

Tier 1 cannot detect a regression that lives in panel response or USB
transport. Tier 2 cannot attribute a regression to a specific compositor stage.
The two are complements. Keep the existing KWin stage telemetry running
alongside both, so a whole-chain change can be traced to a stage.
