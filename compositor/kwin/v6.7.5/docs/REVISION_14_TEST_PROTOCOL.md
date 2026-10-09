# Revision 14 HDR direct-scanout test protocol

Revision 14 is an experimental NVIDIA HDR/WCG direct-scanout candidate. It
compensates mandatory fixed-function PQ curves in the DRM plane graph while
preserving KWin's requested SDR-to-output color transform. It adds no tuning
knobs and does not enable persistent telemetry.

## One-restart installation

From the project root, validate the artifact and install it with capture already
staged:

```bash
./bin/kwin-latencyctl test
./bin/kwin-latencyctl install --capture
```

Then restart the computer once. The installed pacman version remains
`6.7.3-1.1`; package metadata and compiled markers identify project revision
14. This versioning lets a newer official CachyOS package replace the candidate
normally.

After restart:

```bash
./bin/kwin-latencyctl status
```

The kernel-release gate must report active. Booting a different kernel, such as
the LTS recovery kernel, prevents the experiment policy from activating.

## Controlled captures

Keep HDR/WCG and VRR enabled on the 4K 240 Hz output. Use the same game scene
and graphics settings as the revision-13 baseline. Let the fullscreen scene
settle before each capture so Alt-Tab is not part of the steady-state sample.

At a 120 FPS cap:

```bash
./bin/kwin-latencyctl trace palworld-r14-hdr-120
```

Uncapped:

```bash
./bin/kwin-latencyctl trace palworld-r14-hdr-uncapped
```

Also exercise one fallback transition during a separate capture: briefly show
an overlay or Alt-Tab, then return to unobstructed fullscreen. This checks that
composition fallback and direct-scanout re-entry remain correct.

## Acceptance criteria

A successful candidate must satisfy all of these conditions:

- fullscreen attempts are accepted for direct scanout after the scene settles;
- `color_pipeline_unsupported` no longer repeats in steady state;
- atomic DRM commits succeed without fallback loops, NVIDIA Xid errors, or a
  KWin crash;
- colors, SDR brightness, Night Light, HDR metadata, and black levels remain
  visually correct;
- no new flicker appears during steady state or fallback/re-entry;
- the steady-state KWin compositor render stage becomes absent or sparse.

For direct scanout, the absence of a KWin render-duration sample is the desired
result; it should not be interpreted as missing telemetry. Compare the complete
p50, p95, p99, and maximum distributions in nanoseconds for wake-up, render,
presentation test, queue age, DRM commit ioctl, and callback timing. Also check
frame cadence and game performance for regressions.

The revision-13 HDR baseline rejected 150 of 150 fullscreen attempts and had a
post-transition KWin render distribution of 291,623 ns p50, 1,545,012 ns p95,
1,645,219 ns p99, and 1,659,633 ns maximum. Revision 14 succeeds only if live
evidence shows that stage is removed without correctness or stability loss.

KWin tracing cannot measure the display's internal HDR processing. A claim
about end-to-end photon latency requires an external high-speed camera or
photodiode measurement.

## Disable capture and rollback

After collecting both traces, disable capture and restart KWin with a logout or
full reboot:

```bash
./bin/kwin-latencyctl capture-off
```

To restore the official repository package and remove experiment state:

```bash
./bin/kwin-latencyctl rollback
```

Follow the command's restart instruction. The archived revision-13 package is
kept under `artifacts/packages/history/` for controlled A/B work.
