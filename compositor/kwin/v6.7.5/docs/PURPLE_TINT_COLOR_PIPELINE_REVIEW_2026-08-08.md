# Purple tint review: experimental NVIDIA DRM plane color pipeline

Date: 2026-08-08
Trigger: Helldivers 2 showed a purple tint on the focused fullscreen window.
Resolution in effect: `KWIN_DRM_USE_COLOR_PIPELINE=0` in
`~/.config/environment.d/91-kwin-color-pipeline-off.conf`. Colors are normal
after logout and login.

## 1. What the experiment turned on

Patches 0013 through 0016 move one color conversion out of the KWin OpenGL
shader and into NVIDIA fixed-function DRM plane blocks. The goal is direct
scanout of the fullscreen game buffer.

| Patch | Function |
| --- | --- |
| 0013 | Enables `DRM_CLIENT_CAP_PLANE_COLOR_PIPELINE` on NVIDIA |
| 0014 | Corrects the low segment of the inverse sRGB transfer function |
| 0015 | Caches the constructed pipeline outside the frame hot path |
| 0016 | Programs non-bypassable named curves and folds in their inverses |

The measured prize is the compositor render pass: 312,504 ns median at a 120 FPS
cap, and 1,128,000 ns median under high GPU load
(`docs/HDR_SDR_COLOR_PIPELINE_AUDIT.md`, lines 12-15).

### The gate in patch 0013

`patches/0013-exact-kernel-nvidia-color-pipeline.patch`, lines 58-64:

```cpp
const bool allowExperimentalNvidiaColorPipeline = s_experimentKernelAllowed
    && m_drmDevice->isNvidia()
    && m_nvidiaDriverVersion >= Version(610, 43, 3);
const bool colorPipelineRequested = s_colorPipelineEnv.value_or(
    (!m_drmDevice->isNvidia() && !m_drmDevice->isAmdgpu()) || allowExperimentalNvidiaColorPipeline);
```

`s_experimentKernelAllowed` is true when `KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE`
matches `uname -r` exactly. `s_colorPipelineEnv` reads
`KWIN_DRM_USE_COLOR_PIPELINE` and overrides everything, which is why the `0`
value removes the tint.

Upstream KWin disables plane color pipelines on NVIDIA by default. The patch
header states this at lines 6-8. The experiment reverses a deliberate upstream
policy.

### The transform pushed into hardware

Three operations, from the audit document lines 77-90:

1. Gamma 2.2 EOTF, encoded SDR into linear luminance.
2. A 3x4 matrix that carries gamut mapping, reference-luminance scaling,
   black-point compensation, and the Night Light white point.
3. Inverse gamma 2.2, into the BT.2020 nonlinear blending encoding.

The matrix in the audited state:

```text
+2.211726427 +0.604460776 +0.093988739 0
+0.158771753 +2.717468739 +0.033936638 0
-0.007071416 +0.117982179 +2.799264908 0
```

The diagonal gains differ per channel: red 2.212, green 2.717, blue 2.799.
Night Light adds further per-channel factors of 1.151, 0.968, and 0.696.

### The compensation in patch 0016

NVIDIA's `Full` graph contains named PQ curves that no bypass property can
disable. Patch 0016 programs each mandatory curve and puts its mathematical
inverse into a neighboring programmable block. The two new entry points are
`DrmNamed1DLut::bypassScaling()` and `DrmNamed1DLut::bypassOutputScaling()`
(patch lines 528-597).

## 2. Why the display turned purple

### Verified facts

- `ValueRange` holds one scalar `min` and one scalar `max` for all three
  channels (`reference/upstream/kwin-6.7.4/src/core/colorpipeline.h`, lines
  27-35).
- `bypassScaling()` builds the compensating transfer function from that scalar
  range: `TransferFunction transfer(type, nextOperation.input.min,
  nextOperation.input.max)` (patch 0016, lines 548-550).
- Patch 0016 was validated only against a hand-written mock of an assumed
  NVIDIA block sequence, at a tolerance of `1e-5` (patch line 275; audit
  document lines 271-286).
- The audit document states that capability exposure does not prove the
  transform is correct (lines 117-121), and lists visual validation as
  acceptance step 8 (lines 351-352).
- `docs/REVISION_15_TEST_PROTOCOL.md`, line 73, names "purple/green transform
  error" as a specific failure to watch for.

The purple tint is acceptance step 8 returning a negative result. The color
math was never validated against real hardware output before this test.

### Hypothesis 1 — scalar normalization across a per-channel transform

Rank: most likely.

The compensation normalizes a nonlinear PQ curve using one scalar range shared
by red, green, and blue. The requested transform is per-channel. A nonlinear
curve normalized by a shared scalar does not cancel per channel. The residual
error grows with the distance between channel gains.

Green sits between red and blue in the gain order. An error that is monotone in
gain therefore pushes green away from the red/blue pair. A green deficit reads
as magenta or purple. This matches the failure axis the test protocol already
named.

### Hypothesis 2 — the real graph differs from the mock

Rank: plausible, and cheap to test offline.

`pickSupportedFunction()` selects a named curve by a fixed priority order and
takes `PQ_125` first (patch 0016, lines 500-518). If the real block applies a
different curve than the one selected, KWin programs one function and inverts
another. That produces a large color error directly.

The mock models this sequence:

```text
programmable matrix
-> mandatory PQ-125 inverse EOTF
-> programmable LUT
-> mandatory PQ-125 EOTF
-> programmable matrix
```

No record in this repository confirms that the live NVIDIA `Full` graph has
that exact shape.

### Hypothesis 3 — Night Light applied twice

Rank: ruled out by direction.

The CRTC stage keeps its own Night Light multiplier and the design does not
bypass it (audit document lines 92-99). Applying the warm correction twice
would remove blue and produce an amber cast. The observed cast is purple, so
this mechanism predicts the wrong direction.

## 3. Recommended next diagnostic

Dump the real NVIDIA plane graph with the existing read-only probe. This
separates hypothesis 2 from hypothesis 1 without another logout and without
changing display state.

```bash
g++ -std=c++20 -O2 -Wall -Wextra -Wpedantic \
  $(pkg-config --cflags libdrm) \
  tools/drm_color_pipeline_probe.cpp \
  -o /tmp/drm_color_pipeline_probe $(pkg-config --libs libdrm)
/tmp/drm_color_pipeline_probe /dev/dri/card1
```

Compare the printed block order and named-curve enums with the mock sequence
above. A mismatch confirms hypothesis 2.

If the graph matches the mock, the remaining work is hypothesis 1: extend the
compensation to per-channel ranges, or reject the assignment whenever the
requested transform has unequal channel gains across a mandatory nonlinear
curve.

## 4. Status of the patch series

Patches 0013 through 0016 stay in the tree and stay built. Only the runtime
override is off. Deleting
`~/.config/environment.d/91-kwin-color-pipeline-off.conf` and logging in again
restores the experimental path.
