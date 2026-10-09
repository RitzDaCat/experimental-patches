# Direct scanout on NVIDIA: state, root-cause progress, and plan

Date: 2026-08-23
System: RTX 4090, NVIDIA open driver 610.57.04, kernel 7.2.0-1-cachyos,
KWin experiment revision 23 (gate active, opt-in enabled)
Displays: DP-2 PG32UCDP 3840x2160@240.02, scale 1.5, HDR + WCG + VRR;
DP-3 1920x1080@59.99, HDR enabled

## 1. Current state

The compensated color-pipeline matcher (patch 0016) is **built and gated but
runtime-disabled** by `~/.config/environment.d/91-kwin-color-pipeline-off.conf`
(`KWIN_DRM_USE_COLOR_PIPELINE=0`), set after Helldivers 2 showed a purple tint
on the focused fullscreen window
(`PURPLE_TINT_COLOR_PIPELINE_REVIEW_2026-08-08.md`).

The measured prize for re-enabling it correctly is the compositor render pass
on DP-2: **291,623 ns p50 / 1,545,012 ns p95 / 1,645,219 ns p99** (r13
captures), and 312,504 ns median at a 120 FPS cap versus 1,128,000 ns median
under high GPU load (revision 11). At a 4,166,389 ns refresh interval the p95
render stage occupies about 37% of a frame.

## 2. New facts established today

### 2.1 The real NVIDIA graph matches the patch's mock exactly

The read-only DRM probe (`tools/drm_color_pipeline_probe.cpp`, compiled against
libdrm, opened its own fd, client capabilities only, zero atomic commits) dumped
both primary planes on driver 610.57.04. The `NVIDIA Full` chain is:

| Op | Block | Bypass |
| --- | --- | --- |
| 58 | 3x4 Matrix | yes |
| 63 | 1D Curve, PQ-125 EOTF | yes |
| 68 | 1024-entry 1D LUT, linear interpolation | yes |
| 75 | Multiplier | yes |
| 80 | 3x4 Matrix | yes |
| 85 | 1D Curve, **PQ-125 Inverse EOTF** | **no** |
| 89 | 3x4 Matrix | yes |
| 94 | 1024-entry 1D LUT, linear interpolation | yes |
| 101 | 3x4 Matrix | yes |
| 106 | 1D Curve, **PQ-125 EOTF** | **no** |
| 110 | 3x4 Matrix | yes |

Block order, named-curve enums (`CURVE_1D_TYPE=2/3` only), and bypass placement
are identical to the mock sequence patch 0016 was validated against. Both
primary planes (DP-2 and DP-3) expose the same four shapes; overlay planes get
Lite and FP Lite.

**Hypothesis 2 from the purple-tint review (real graph differs from the mock)
is ruled out.**

### 2.2 The matcher and atomic path succeed end-to-end; only chromatic
correctness fails

Re-reading the r14 capture
(`artifacts/results/20260722-192031-dark-and-darker-r14-color-fail-trace/`):

- Direct-scanout reasons on DP-2: `{'accepted': 105}`, zero failed DRM commits.
- The trace label "color-fail" refers to the observed color error while scanout
  was active; the control run at 21:17 the same day
  (`20260722-211711-dark-and-darker-policy-off-correct`) shows correct colors
  with the pipeline off.

So on real hardware the full path — early check, assignment search, blob
programming, atomic validation, flip — completes. The blocker is not
acceptance. It is that the programmed hardware transform computes a visibly
different result than the reference `ColorPipeline`.

### 2.3 Driver drift is benign so far

The incident and all prior probes were on 610.43.03. The system now runs
610.57.04 and the exposed graph is unchanged (section 2.1). The patch 0013 gate
(`>= 610.43.03`) remains satisfied.

## 3. Ranked remaining hypotheses for the color error

With hypothesis 2 dead, the candidates are:

### H1a — RESOLVED by driver source: PQ domain convention of the mandatory CSC stages (confirmed as the dominant risk)

The vendored NVIDIA open driver source
(`reference/upstream/nvidia-open-610.43.03/kernel-open/nvidia-drm/nvidia-drm-color-pipeline.c`)
settles where the mismatch lives:

1. The atomic commit handler (`plane_update_state_from_colorops`) **never reads**
   the `pq_inv_eotf`/`pq_eotf` colorop states. The two mandatory stages are
   fixed hardware functions; nothing userspace programs changes what they apply.
2. The driver's own comment states the conventions differ: "DRM_COLOROP_1D_CURVE_PQ_125_EOTF
   expects 10,000 nits to map to 125.0, but NV_DRM_TRANSFER_FUNCTION_PQ expects
   10,000 nits to map to 1.0". It bridges ONLY the bypassable DEGAMMA path to
   the UAPI convention via an implicit degamma multiplier (`pq_implicit_mult`).
   No bridge exists for the mandatory CSC0LUT/CSC1LUT stages.

Patch 0016 compensates the mandatory stages under the UAPI (×125) convention.
If the fixed stages actually apply the internal (×1.0) convention, the composed
transform is wrong by a full PQ-domain factor — enormous in dark tones where PQ
is steepest.

The offline harness quantified both worlds against the probed Full graph with
hardware-faithful quantization (S31.32→S15.16 matrix truncation per
`ctm_val_to_csc_val`, UNORM16 TMO surface, FP16 ILUT surface):

| hardware \ KWin assumes | 125 (UAPI) | 1 (internal) |
| --- | --- | --- |
| 125 (UAPI) | max 0.096 nits (NL off) / 0.58 nits (NL on) | mean linear err ~31,000 nits |
| 1 (internal) | mean linear err 94.9 nits (NL off) / 73.5 nits (NL on), ~322k domain clamps | max 0.51 nits, zero clamps |

A matched assumption is correct to LUT-quantization level under EITHER
convention; a mismatch is catastrophically loud. This also retroactively
downgrades H1a/H1b/H4 below: the matcher's range bookkeeping is provably
self-consistent; only the untestable hardware convention remains open.

### H1b/H4 and the scalar-envelope family — DOWNGRADED by harness evidence

The harness runs the real patched matcher end-to-end. Under a matched
convention the composed hardware transform matches KWin's reference pipeline
to ≤ 0.6 nits of 420 across a 48³ grid including Night Light, so scalar-range
bookkeeping, clamp insertion, and matrix placement produce no measurable
residual in KWin's own model. They remain relevant only if a future driver
changes graph semantics.

### Ruled out or unlikely

- **H2 wrong mock**: ruled out (section 2.1).
- **H3 Night Light applied twice**: ruled out in the earlier review by direction
  of the error (would be amber, not purple).
- **H5 PQ-125 domain (80 vs 125)**: fixed in patch 0016
  (`namedTransferFunctionScale()` returns 125.0); superseded by patch 0021.
- **H6 LUT quantization**: modeled explicitly in the harness (FP16 ILUT,
  UNORM16 TMO, S15.16 matrices); contributes ≤ 0.6 nits, not a hue cast.

## 4. What was built (2026-08-23, this session)

### Offline harness — `tools/colorscanout_harness/`

Links KWin's installed core color math (`libkwin`) and compiles the REAL
patched matcher (`reference/harness/kwin/drm_colorop.cpp` = upstream 6.7.4 +
patches 0016 + 0017 + 0021) against mock DRM plumbing that records everything
KWin programs. It reconstructs the live display config (PG32UCDP EDID
primaries, HDR/WCG, 300 nit SDR reference, 420 nit peak, Night Light on/off),
runs the actual assignment search, reads back the programmed blobs, simulates
the NVIDIA Full chain with hardware-faithful quantization, and compares
against the reference `ColorPipeline::evaluate` over a dense grid.

Run:

```bash
g++ -std=c++20 -O2 -fPIC \
  -I tools/colorscanout_harness/mockinc -I reference/harness/kwin \
  -I/usr/include/kwin $(pkg-config --cflags libdrm Qt6Core Qt6Gui) \
  tools/colorscanout_harness/harness_main.cpp reference/harness/kwin/drm_colorop.cpp \
  -o /tmp/colorscanout_harness $(pkg-config --libs Qt6Core Qt6Gui) -lkwin
/tmp/colorscanout_harness 125            # simulate UAPI-convention hardware
KWIN_DRM_NVIDIA_CSC_PQ_SCALE=1 /tmp/colorscanout_harness 1   # internal-convention pair
```

### Patch 0021 — runtime-selectable mandatory CSC PQ scale

`patches/0021-selectable-mandatory-csc-pq-scale.patch`: the PQ scale used for
the two MANDATORY named-curve stages becomes runtime-selectable via
`KWIN_DRM_NVIDIA_CSC_PQ_SCALE` ("1" or "125"), defaulting to 125 (UAPI,
unchanged behavior). Bypassable named curves always stay at 125 because the
driver bridges them explicitly. Wired into PKGBUILD and
`scripts/verify_reference_sources.sh`; covered by `tests/test_csc_pq_scale.py`.
The whole series applies clean and byte-compares against the patched overlay
(`reference verification passed`, 103 tests OK).

## 5. Plan

### Step 1 — DONE: offline numerical harness against the proven-real graph

See section 4. The matcher's range bookkeeping is exonerated; the only open
variable is the hardware's mandatory-stage convention, which is unknowable
offline by construction (fixed function, no readback).

### Step 2 — DONE in principle: convention made switchable instead of guessed

Patch 0021 turns the untestable assumption into a single controlled experiment
variable with a fail-safe default.

### Step 3 — live discrimination test (one logout, three states)

With `KWIN_DRM_USE_COLOR_PIPELINE` re-enabled and the capture pattern from
`tools/color-validation-pattern.ppm` fullscreen on DP-2:

1. control: pipeline off (stock composition) — correct reference colors;
2. `KWIN_DRM_NVIDIA_CSC_PQ_SCALE=125` — if colors match control, the hardware
   follows the UAPI convention and patch 0021 is done;
3. `KWIN_DRM_NVIDIA_CSC_PQ_SCALE=1` — if THIS matches control instead, set it
   persistently; either way exactly one state is visually indistinguishable
   from control and that state ships.

Then run the existing validation ladder (VRR uncapped, native HDR, SDR mode,
cursor/overlay fallback, alt-tab/lock/DPMS) plus reason-code histograms and
nanosecond render-stage deltas for the accepted-scanout case.

### Step 4 — coverage beyond color ("all games and situations")

Once correctness holds, enumerate the remaining non-color rejection classes
from telemetry reason codes and size each before touching anything: windowed
and borderless-fullscreen clients, fractional-scale buffer geometry (scale 1.5),
effects/overlay interference (OBS capture), XWayland surfaces, and native-HDR
clients (identity-pipeline path). Each gets its own reason-code histogram and
nanosecond render-stage delta before and after.

### Runtime safety

`KWIN_DRM_USE_COLOR_PIPELINE=0` stays in place until Step 1 produces a
numerically clean composition. Re-enablement then follows Step 3's ladder, one
logout per state change.

## 6. Evidence trail for this document

- Live probe output, `/dev/dri/card1`, 2026-08-23 (section 2.1 tables).
- `artifacts/results/20260722-192031-dark-and-darker-r14-color-fail-trace/summary.md`
  (accepted:105, zero commit failures).
- `artifacts/results/20260722-211711-dark-and-darker-policy-off-correct`
  (control).
- Patch sources: `patches/0016-compensate-mandatory-color-pipeline-curves.patch`
  lines 330-435 (matcher integration) and 480-600 (`bypassScaling`,
  `bypassOutputScaling`, `namedTransferFunctionScale`).
- `~/.config/environment.d/91-kwin-color-pipeline-off.conf` (runtime state).
- NVIDIA driver source: `reference/upstream/nvidia-open-610.43.03/kernel-open/nvidia-drm/nvidia-drm-color-pipeline.c`
  (implicit degamma bridge comment; commit handler never touches CSC stage
  states) and `kernel-open/nvidia-drm/nvidia-drm-crtc.c`
  (`ctm_val_to_csc_val` matrix quantization, ILUT/TMO surface formats).
- Harness decision matrix and per-block assignment dumps (section 4 command).
