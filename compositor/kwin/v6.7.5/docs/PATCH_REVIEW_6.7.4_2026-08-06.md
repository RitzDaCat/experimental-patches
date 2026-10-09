# KWin 6.7.4 compatibility check and patch review — 2026-08-06

Scope: patches/0001–0018 against KWin 6.7.4 (CachyOS `kwin 6.7.4-1.1`).
Method: real patch application, byte-compare, upstream diff audit, full read of all 18 patches.

## 1. Compatibility verdict: patches still needed, no rebase required

| Check | Result | Evidence |
|---|---|---|
| Installed kwin | 6.7.4-1.1 (stock CachyOS, installed 2026-08-06 01:58) | `pacman -Qi kwin` |
| Pending update | none — repo == installed | `checkupdates` exit 2 |
| Patches merged upstream in 6.7.4? | No. All 18 applied forward; none detected as "previously applied" | patch log below |
| Apply result on 6.7.4 | 18/18 apply. 0003 one hunk fuzz 1; 0003/0013/0014 line offsets only | `scratchpad/patch-apply-6.7.4.log` |
| Patched files changed upstream 6.7.3→6.7.4? | 0 of 35. Upstream changed 165 files; none overlap the patch set | `diff -rq` both trees |
| Result identical to verified 6.7.3 overlay? | Yes. All 35 touched files byte-identical after patching both trees | `cmp` loop, zero DIFFERS |
| Upstream changes near the patches | 4 source files: KWIN_RENDER_NODES device selection, virtual-layer buffer reset, epoxy GPU-reset handler, KWIN_DRM_DEVICES parsing move. All orthogonal | diffs read in session |

The fuzz in 0003 comes from patch-on-patch context (0001/0002 shift lines), not from 6.7.4.
The byte-compare proves the fuzzed hunk landed at the correct location.

Build of the patched 6.7.4 tree: **not run in this session — unverified**.
The sources equal the overlay that built and ran as 6.7.3-1.1, so a clean build is expected.

### Machine state (important)

The 6.7.4 update **replaced the patched package**. The local PKGBUILD builds `pkgname=kwin`
at 6.7.3-1.1; pacman upgraded it to the stock CachyOS 6.7.4-1.1. The running compositor
has none of the 18 patches until a rebuild + reinstall + re-login.

To rebuild: set `pkgver=6.7.4`, `pkgrel=1.1` in PKGBUILD and update the tarball sha256 to
`db7a7dba71aaca1e5218733b80f90a998d84e2ab36e4d62d0e3ea00376c5802d`
(verified against `https://download.kde.org/stable/plasma/6.7.4/kwin-6.7.4.tar.xz`).

Gate/env state (`~/.config/environment.d/90-kwin-latency.conf`):
- `KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE=7.1.5-1-cachyos` — **matches** running kernel. The stale-gate problem from Aug 3 is resolved on disk.
- `KWIN_ADAPTIVE_COMPOSITOR_MARGIN=2` (adaptive live), `KWIN_VRR_REPAINT_COALESCING=1` (on).
- `KWIN_ADAPTIVE_RENDER_BUDGET` **not set** → patch 0009's render budget runs in stock mode.
- `KWIN_LATENCY_CAPTURE` not staged → capture off until `kwin-latencyctl capture-on`.

## 2. Code review

Overall: the set is disciplined. Every behavior change sits behind the exact-kernel gate
plus its own opt-in variable. With the gate off, the code compiles to the stock QBasicTimer
path plus a handful of cached-boolean branches. No correctness bug found in the
normal (gate-off or telemetry-off) paths.

### Findings, ranked

1. **Capture-mode only — file I/O under the commit-thread mutex** (0011/0017,
   `drm_commit_thread.cpp`). `pageFlipped()` writes the CSV row, and since 0017 flushes
   every 256 rows, while `m_mutex` is held. The commit thread blocks on that mutex to
   submit. A slow flush can delay an atomic commit by microseconds to milliseconds
   during capture runs. Normal mode is untouched. Fix if desired: copy the sample,
   unlock, then write/flush (same pattern 0007 already uses for input telemetry).
2. **Latent trap — `PreciseTimer::start(0ns)` disarms instead of firing** (0001 semantics,
   used by 0002/0010). `timerfd_settime` with `it_value == 0` disarms, but `m_active`
   becomes true. No current call site can pass 0 while the coalescing path is active
   (`foregroundDeadline` is clamped to `currentTime`). A one-line clamp
   (`std::max(deadline, 1ns)`) in `PreciseTimer::start` removes the trap permanently.
3. **0014 belongs upstream.** The inverse-sRGB linear-segment fix (`/12.92` → `*12.92`)
   is a genuine KWin bug with a test. Submit it to KDE; it reduces your patch debt by one.
4. **Duplication (cosmetic):** `latencyCaptureEnabled()` / the uname gate is copy-pasted in
   5 files (renderloop, connection, commit thread, compositor, outputlayer, colorop).
   One shared helper would keep the release-string logic in one place.

### Design points that hold up well

- Fail-closed everywhere: wrong kernel → stock timer, stock 1 ms margin, no telemetry,
  NVIDIA color pipeline stays off (0005/0013 both re-check uname).
- Cache keys hold `shared_ptr` copies (0015 shader uniforms, identity cache, scanout
  pipeline cache). That pins the objects, so pointer-identity keys cannot ABA.
- 0009 keeps the stock 2 ms GL prediction floor via `RenderTimeSpan::predictionFloor`
  and still feeds the stock-clamped duration to the render journal. Modes 0/1 are
  bit-for-bit stock predictions.
- The adaptive controllers use second-largest-in-window statistics with immediate
  debt payment and slow decay, per presentation path, with refresh-relative bounds
  (at 240 Hz: margin ceiling ≈ 1.04 ms, floor ≈ 16 µs). External-stall fallback
  restores the configured reserve after 2 outliers per 256-sample window.
- 0016 ships a numeric autotest that walks the mocked NVIDIA Full graph across
  negatives, the PQ-125 boundary, and 232-nit inputs against the requested transform.
- 0018 is a correct no-behavior-change guard; one armed wake now trains at most once.

## 3. Performance assessment

Short answer: the mechanisms are nanosecond-precise, but the wins are microseconds to
milliseconds. That is the right direction — the latency budget was dominated by
scheduling reserves, not by slow code.

| Lever (patch) | State on this machine | Magnitude | What it affects |
|---|---|---|---|
| timerfd wakeups (0001/0002) | active once rebuilt | kills Qt ~1 ms timer rounding | wake precision; enables the next two rows |
| Adaptive wake margin (0004/0006/0009) | **on** (mode 2) | fixed 1 ms → learned ~0.1–0.3 ms; saves ~0.7–0.9 ms | compositing starts later → fresher input each frame |
| Adaptive render budget (0009) | **off** (env var absent) | up to ~1.5–2 ms for light scenes (removes 2 ms floor) | same, second reserve |
| NVIDIA color pipeline + curve compensation (0013/0016) | active once rebuilt (driver 610.43.03 ✓) | ~0.3–1 ms GPU + removes a composite pass | fullscreen SDR-on-HDR gets direct scanout — biggest gaming lever |
| VRR repaint coalescing (0010) | **on** | pacing/jitter, not average: background damage waits for game cadence instead of fixed 33 ms timer | overlay/notification-induced stutter under VRR — directly relevant to the D4 case |
| Color hot-path caches, opaque shader, tonemap hoist (0015) | always on when built | µs-scale CPU per frame; per-pixel GPU ALU cuts | composited-frame render time |
| sRGB segment fix (0014) | always on | correctness, not speed | dark-tone accuracy below encoded 0.04045 |
| Telemetry (0003/0007/0008/0011/0012/0017) | off until capture-on | 0 when off; ~25 ns clock reads, sampled 1/64, when on | measurement, not latency |

Per-axis verdict:

- **Input latency:** the input stack itself is not made faster; it is measured. The
  effective input-to-photon win comes from later compositing starts (margin + budget):
  roughly 1–3 ms fresher input on the composited VSync path when both controllers run.
- **Render latency:** execution gets µs-scale cuts (0015); scheduling gets ms-scale
  cuts (margin/budget). The frame reaches the display earlier mainly because it
  starts later and misses less.
- **Gaming latency:** the ms-class lever is direct scanout on HDR (0013/0016) — it
  removes the compositor render entirely for fullscreen content. 0010 attacks stutter
  cadence rather than average latency. Nothing here is a "nanosecond improvement";
  ns-only effects (branch checks, const-ref returns) are noise below measurement.

## 4. Next steps

1. Bump PKGBUILD to 6.7.4 with the sha256 above.
2. Rebuild and reinstall the package (long build — schedule it).
3. Re-login, then verify: `systemctl --user show-environment | grep KERNEL_RELEASE` → `7.1.5-1-cachyos`.
4. Optional: add `KWIN_ADAPTIVE_RENDER_BUDGET=2` (or `1` for shadow-learn first) to the env file.
5. Resume the D4 A/B plan — the reason-coded scanout telemetry needs this rebuild to exist at all.

Evidence artifacts: `patch-apply-6.7.4.log`, pristine 6.7.4 tree, and both patched trees
live in the session scratchpad (`.../scratchpad/`).
