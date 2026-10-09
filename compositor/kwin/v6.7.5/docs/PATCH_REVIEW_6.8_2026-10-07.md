# KWin 6.8 upstream status check and rebase assessment — 2026-10-07

Scope: patches/0001–0021 (revision 24, base 6.7.5-1.1) against upstream
`Plasma/6.8` at `5e1853d5f6` (2026-10-07, after `v6.7.91` = 6.8 Beta 2).
Method: fetched upstream into the local clone, diffed every overlay file
between `v6.7.5` and `Plasma/6.8`, read the commits that touch them, and
applied the series with `patch -Np1 -f` onto a `git archive` of the branch.

## 1. Situation

| Fact | Value | Evidence |
|---|---|---|
| Installed | kwin 6.7.5-1.1 revision 24, kernel 7.2.9-1-cachyos-custom | `pacman -Qi kwin`, `uname -r` |
| CachyOS repo | kwin 6.7.5-1.1 (sync db refreshed 2026-10-07) | `pacman -Si kwin` |
| Plasma 6.8.0 | tag Thu 2026-10-08, release Wed 2026-10-14; 6.8.1 2026-10-20 | community.kde.org/Schedules/Plasma_6 |
| Plasma 6.7.6 | Tue 2026-11-03 (last 6.7 bugfix before 6.7.7 in January) | same |
| Upstream delta | 823 commits 6.7.5 → Plasma/6.8; 1,450 files | `git rev-list --count` |
| Overlay delta | 31 of 35 overlay paths differ (+1,373 / −743); two are the PreciseTimer files, now upstream | `git diff --stat v6.7.5 origin/Plasma/6.8 -- <overlay>` |

Per the versioning policy the CachyOS 6.8.0 package will replace this one
during a normal upgrade, and the `kwin-latency-kwin-replaced` hook will say so.
The series goes dark at that moment; nothing breaks.

## 2. Verdict: a real rebase this time, and two patches are gone

The 6.7.4 and 6.7.5 bumps applied with offsets only. 6.8 does not. Upstream
restructured the render loop, the DRM commit thread API, the OutputLayer
frame API, the compositor's direct-scanout ordering, the GL render-time query
and the shader path. Every patch that touches `renderloop.cpp`,
`compositor.cpp` or `src/opengl` needs manual work.

Apply result on the 6.8 tree (0001/0002 skipped because they are upstream):

| Patch | Hunks | Failed | Rejects in |
|---|---|---|---|
| 0003 wakeup instrumentation | 7 | 1 | renderloop_p.h |
| 0004 adaptive wakeup margin | 7 | 3 | renderloop.cpp, renderloop_p.h |
| 0005 kernel release gate | 14 | 5 | renderloop.cpp, renderloop_p.h |
| 0006 adaptive margin v2 | 12 | 3 | renderloop.cpp, renderloop_p.h |
| 0007 libinput telemetry | 12 | 0 | — (offsets only) |
| 0008 telemetry sampling | 16 | 2 | renderloop.cpp, renderloop_p.h |
| 0009 adaptive render budget | 19 | 7 | renderloop.cpp, renderloop_p.h, glrendertimequery.cpp |
| 0010 VRR cadence coalescing | 11 | 3 | renderloop.cpp, renderloop_p.h |
| 0011 bounded latency capture | 36 | 8 | drm_commit_thread.cpp, compositor.cpp, renderloop.cpp, renderloop_p.h |
| 0012 reason-coded capture | 9 | 1 | compositor.cpp |
| 0013 NVIDIA color pipeline gate | 3 | 1 | drm_gpu.cpp |
| 0014 inverse sRGB fix | 3 | 1 | colorspace.cpp (context only) |
| 0015 color hot-path cache | 30 | 8 | compositor.cpp, colormanagement.glsl, glshader.cpp, glshadermanager.{cpp,h}, itemrenderer_opengl.h, test_colorspaces.cpp |
| 0016 mandatory curve compensation | 19 | 0 | — (offsets only) |
| 0017 frame and color capture | 30 | 2 | compositor.cpp |
| 0018 wake-sample guard | 1 | 1 | renderloop.cpp |
| 0019 default policy / timer clamp | 5 | 3 | drm_gpu.cpp, renderloop.cpp |
| 0020 runtime opt-in policy | 11 | 5 | renderloop.cpp |
| 0021 CSC PQ scale | 8 | 0 | — (offsets only) |

Failures cascade inside `renderloop.cpp`, so the per-patch numbers overstate
the work there; the cluster view in section 5 is the honest estimate.

## 3. Per-patch upstream status

| Patch | Upstream status in 6.8 | Verdict |
|---|---|---|
| 0001 PreciseTimer | Merged: `797d0820`, in v6.7.90+ | **Drop** |
| 0002 renderloop timerfd | Merged: `cd46f9c9`, in v6.7.90+ | **Drop** |
| 0003 wakeup instrumentation | Not upstream. showfps now shows CPU and GPU render time (`2942bdae98`) but the perf CSV has no wake-delivery columns | Keep, small rework |
| 0004/0006 adaptive wake margin | Not upstream. `scheduleRepaint` still does `renderJournal.result() + safetyMargin + 1ms` (renderloop.cpp:61). The timerfd merge removed the millisecond truncation, **not** the 1 ms allowance | Keep, rework onto the new `scheduleRepaint(lastTarget, presentNotBefore)` |
| 0005 kernel release gate | n/a | Keep, mechanical |
| 0007/0008 input telemetry | Not upstream; connection.cpp changed by 12 lines (scroll lock, empty-outputs guard) | Keep; 0008's renderloop hunks follow the 0004 rework |
| 0009 adaptive render budget | Partly overtaken. The 2 ms floor moved from `GLRenderTimeQuery` into `RenderLoopPrivate::notifyFrameCompleted` (`5338c2e9a7`); the GL query now reports a GPU-only span and the CPU span comes from `OutputFrame::queryCpuRenderTime()` (`788c84c83a`, `2942bdae98`) | Keep, **redesign plumbing**: the glrendertimequery hunk and `predictionFloor` are obsolete; the learner must pick GPU, CPU or union span explicitly |
| 0010 VRR cadence coalescing | Not upstream. `delayedVrrTimer` is still a `QBasicTimer` at a fixed 1000 ms / 30 (renderloop.cpp:291) | Keep, rework |
| 0011/0017 capture | Not upstream. `DrmCommitThread::pageFlipped/setModeInfo` now return the margin and `safetyMargin()` is gone (`1dc43e34a6`); pageflips match unique commit IDs (`8187d8ee57`); `OutputLayer::beginFrame(OutputFrame*)` is virtual and `doBeginFrame/doEndFrame` are gone (`aaed814f77`); the compositor attempts direct scanout before `prepareRendering` and matches color pipelines inside `importScanoutBuffer` (`2a4806495d`, `1ad3160364`) | Keep only if capture mode is still wanted; largest rework |
| 0012 reason-coded capture | Partly overtaken: `OutputLayer::presentedDirectScanoutItem()` and the zero-copy presentation-feedback flag (`41a7a8b3c7`) now expose *whether* scanout happened, not *why* | Keep, rework; build on the upstream getter |
| 0013 NVIDIA color pipeline gate | **Obsolete.** 6.8 sets `DRM_CLIENT_CAP_PLANE_COLOR_PIPELINE` by default on every driver, NVIDIA and AMD included (drm_gpu.cpp:207; 6.7.5 excluded both) | **Drop**; see the hazard below |
| 0014 inverse sRGB fix | **Not fixed.** `sRGBinverseEOTF` still divides by 12.92 (colorspace.cpp:803); the GLSL multiplies | Keep (one-line context refresh) and **submit upstream** |
| 0015 color hot-path cache | Not upstream. The shader path changed underneath it: one item renderer per render device (`01390f9f39`, `ad28dc8caa`), desktop GL dropped (`16b21b5e18`), premultiplied QColor uniforms (`c908a32618`), always clip to source range (`2a811c6489`), HLG (`2ccdca3eb7`) | Rework and **re-benchmark** before keeping; candidate to drop if the µs-scale win does not survive |
| 0016 mandatory curve compensation | **Not upstream.** 6.8 still rejects a pipeline when a non-bypassable op is left over (`bdf2ed2ae1`, `44b4557b5c`); it adds `FixedMatrix` YUV ops, 128-entry LUTs and interpolation enums, all orthogonal | Keep; **add an explicit gate** (hazard) |
| 0018 wake-sample guard | n/a | Fold into the 0004/0006 rework |
| 0019 defaults, timer clamp, NVIDIA opt-in | `PreciseTimer::start` has no ≤ 0 clamp upstream (deadline 0 disarms, negative is `qFatal`); the NVIDIA opt-in is now inverted by the upstream default | Split: keep the clamp as its own patch and **submit upstream**; redo the policy defaults; re-decide NVIDIA |
| 0020 runtime opt-in policy | n/a | Keep, rework with the renderloop cluster |
| 0021 CSC PQ scale | Not upstream | Keep as is |

### Hazard: NVIDIA plane color pipelines are on by default in 6.8

Two consequences, one for stock users and one for this series.

- Stock 6.8 on this box: the NVIDIA Full graph carries non-bypassable CSC
  stages, so upstream's matcher will reject every non-identity pipeline and
  fall back to shader composition. That is no purple tint but also no direct
  scanout for SDR-on-HDR, the exact blocker 0016 attacks. Whether the
  identity path (SDR output) scans out cleanly on stock 6.8 is a free data
  point for the C1 discrimination test; check it before rebasing.
- This series on 6.8: 0016 has no gate of its own. It runs whenever the
  plane pipeline is active, which 0013 and 0019 used to keep opt-in on
  NVIDIA. With the upstream default on, the unvalidated compensation would be
  live by default. At rebase, either gate 0016/0021 on the kwinrc policy
  switch from 0020, or have the series default `KWIN_DRM_USE_COLOR_PIPELINE`
  off on NVIDIA until the live test in
  `DIRECT_SCANOUT_NVIDIA_INVESTIGATION_2026-08-23.md` §5 has run.

## 4. What upstream changed that the design cares about

- **Commit timing landed (C4).** `wp_commit_timing_v1` (`e29d8f8412`) and a
  "present not before" timestamp through `scheduleRepaint` (`1e1eecfbe9`).
  Drop C4 from the ladder; G5 (client side) is now the follow-up. The
  adaptive margin must keep `presentNotBefore` semantics intact: a later
  wake is only allowed when it still meets the earliest requested target.
- **The 1 ms allowance survived the timerfd merge.** The README's claim
  "truncated to whole milliseconds and a fixed 1 ms allowance" becomes "a
  fixed 1 ms allowance" for 6.8. The reserve the margin controller removes
  is now exactly that allowance plus the DRM margin, nothing from Qt.
- **C2 and C3 are untouched.** `RenderJournal` is byte-identical between
  6.7.5 and 6.8; the commit-thread margin still adds lateness immediately and
  decays surplus at 1/10 per frame, clamped to min(3 ms, vblank/2)
  (drm_commit_thread.cpp:169–181). Both levers remain open.
- **Render time is split.** GPU-only from the GL query, CPU from the
  compositor, 2 ms floor applied in the render loop. 0009 gets simpler
  (the floor is in a file the series already owns) but must say which span
  it budgets.
- **Safety margin is now passed by value** from the commit thread under its
  lock. 0011/0017's commit-thread hooks sit on functions whose signatures
  changed; the earlier review's finding about file I/O under `m_mutex`
  is the right moment to fix while re-plumbing.
- **Direct scanout path reordered.** Scanout is attempted before rendering
  is prepared, pipelines are matched during buffer import, a single
  fullscreen layer's trailing encode can be offloaded to the CRTC post-blend
  gamma (`9ca199df4d`), and the legacy CTM is no longer programmed on
  plane-pipeline hardware (`25f3db3ef3`). 0012/0017's phase timestamps and
  reason codes must be re-anchored to the new decision points.
- **GL ES only, one renderer per render device.** 0015's shader-level
  caches (`glshader`, `glshadermanager`, `itemrenderer_opengl`) land on
  code that was rewritten; the opaque-surface specialisation needs
  re-measuring with the new "clip to source range" ALU in the same shader.

## 5. Rebase plan and effort

Order by dependency and risk; sizes in story points on the project scale.

1. **Packaging (2).** `pkgver=6.8.0`, CachyOS `pkgrel`, new tarball sha,
   drop the two `invent.kde.org` sources and their `prepare()` lines, keep
   the `KWIN_LATENCY_BAKED_KERNEL_RELEASE` export. Dependency floors moved:
   Qt ≥ 6.11, KF6 ≥ 6.30, wayland ≥ 1.26, wayland-protocols ≥ 1.49,
   plasma-wayland-protocols ≥ 1.23, libdrm ≥ 2.4.127, pipewire ≥ 1.4;
   `KWIN_BUILD_SCREENLOCKER` and both `check()` test targets still exist.
   Copy the CachyOS 6.8 PKGBUILD depends rather than hand-editing.
2. **Color cluster (2).** 0014 context refresh; 0016/0021 apply as is but
   gain the explicit gate; 0013 dropped; the 0019 timer clamp becomes a
   one-hunk patch. Submit 0014 and the clamp to KDE in the same week.
3. **Render-loop cluster (5).** 0003–0006, 0008, 0009, 0010, 0018, 0019
   policy, 0020. Re-derive on the 6.8 `scheduleRepaint`; fold 0018 in;
   rewrite 0009's span plumbing; keep the controllers' nanosecond state
   and refresh-relative bounds unchanged so the replay tests still hold.
4. **Capture cluster (5, optional).** 0011, 0012, 0017. Decide first
   whether bounded capture is still the measurement path or whether the
   Tier-1 input-to-photon rig replaces it; if the latter, drop all three and
   the stack shrinks by ~1,900 lines.
5. **0015 (3).** Rework last, and only after a benchmark on 6.8 shows the
   per-frame CPU and ALU savings survive the upstream shader changes.
6. **Reference and docs (1).** Regenerate `reference/patched-overlay`,
   `scripts/verify_reference_sources.sh`, README claim table,
   `SCHEDULING_MODEL_AND_CLAIMS.md` first row, this table.

Do not start on `v6.7.91`; 6.8.0 tags tomorrow and the CachyOS package
follows within days. The scratch apply above is against the branch head and
is what 6.8.0 will contain.

## 6. Open question the rebase should answer first

Install stock 6.8 when CachyOS ships it, keep the series dark, and record on
this box: does fullscreen SDR-on-HDR content direct-scan-out, composite, or
tint? That single observation decides whether 0016/0021 stay opt-in,
become default behind the gate, or are superseded by an upstream fix in
6.8.x.

## 7. Reproducing this review

A clone of upstream KWin holds `origin/Plasma/6.8`, `origin/master` and tags
through `v6.7.91` after `git fetch origin`. Set `bundle` to this directory.

```bash
cd /path/to/kwin
git diff --stat v6.7.5 origin/Plasma/6.8 -- $(git -C "$bundle" ls-files reference/patched-overlay | sed 's|reference/patched-overlay/||')
git log --format='%h %ad %s' --date=short v6.7.5..origin/Plasma/6.8 -- src/core/renderloop.cpp src/backends/drm src/compositor.cpp

work=$(mktemp -d) && git archive origin/Plasma/6.8 | tar -x -C "$work"
for p in "$bundle"/patches/00{03..21}-*.patch; do
    patch -d "$work" -Np1 -f --no-backup-if-mismatch -i "$p" | grep -E 'FAILED|rejects' || true
done
rm -rf "$work"
```
