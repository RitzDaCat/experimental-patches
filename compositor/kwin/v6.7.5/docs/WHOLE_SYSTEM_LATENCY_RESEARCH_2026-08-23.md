# Whole-system interactive-latency research: games, browsers, OS

Date: 2026-08-23
Method: live read-only audit of the running system plus source-level review,
layered on top of `COMPOSITOR_LATENCY_RESEARCH_2026-08-08.md`. Every item is
tagged with its evidence status. Prizes are stated in nanoseconds/milliseconds
with their source; nothing here claims an improvement until measured on this
machine.

## 1. Live system profile (audited today)

| Component | State |
| --- | --- |
| CPU | Ryzen 7 9800X3D, single CCD, governor + EPP `performance`, one NUMA node |
| Kernel | 7.2.0-1-cachyos, `mitigations=off split_lock_detect=off nowatchdog zswap.enabled=0`, swappiness 150 |
| sched_ext | **Installed (`scx-scheds` 1.1.2) but `disabled`** — EEVDF-class policy active |
| GPU | RTX 4090, NVIDIA open 610.57.04, `nvidia-drm.modeset=Y`, observed P2 while queried |
| Displays | DP-2 3840x2160@240.02 scale 1.5 HDR+WCG VRR-auto; DP-3 1080p@60 HDR+WCG |
| Compositor | KWin revision 23, gate active, opt-in on; color pipeline runtime-off |
| Games | Steam native, `proton-cachyos-slr 11.0.20260703` (dxvk-low-latency + vkd3d-low-latency built in), gamescope 3.16.23 installed, MangoHud installed |
| Browsers | Firefox native, Chromium native, Google Chrome as Flatpak |
| Audio | PipeWire 1.6.8, no forced quantum (default 48 kHz graph) |
| Vulkan | Mesa 26.2.1 loader; **NVIDIA ICD exposes `PRESENT_MODE_FIFO_LATEST_READY_KHR`** |

Already optimal in the kernel command line: mitigations off, split-lock
mitigation off, watchdogs off, zswap off. Nothing to gain there.

## 2. Headline

Three zero-build levers were confirmed live on this machine today, none of
which require touching KWin:

1. **`PRESENT_MODE_FIFO_LATEST_READY_KHR` exists on your driver.** Plain FIFO
   present mode holds completed frames hostage to queue depth; latest-ready
   always presents the freshest finished frame. Under GPU load this removes
   whole-frame-queue latency that no compositor patch can reach.
2. **The Proton latency-sleep flags are built into your installed runner**
   (`proton-cachyos-slr` ships `dxvk-low-latency` and `vkd3d-low-latency`) and
   remain unset for your games. Reflex-class latency control is worth
   2–18 ms on GPU-bound titles in external measurement.
3. **sched_ext is installed but disabled.** The interactive schedulers
   (`scx_flash`, `scx_lavd`, `scx_bpfland`, `scx_cake`) target exactly the
   wakeup-jitter tail this project measures at nanosecond granularity.

Everything else in this document ranks below these three in expected value.

## 3. Game render path

### G1 — FIFO-latest-ready adoption (zero build)

| | |
| --- | --- |
| Mechanism | Vulkan present mode that scans out the newest completed frame instead of the oldest queued one |
| Prize | Up to `queue depth × frame time` under GPU saturation; at 120 FPS with a 3-deep queue that is up to ~25,000,000 ns of worst-case staleness removed; typical steady-state win smaller but recurring |
| Evidence | Extension enumerated live on 610.57.04; Mesa-side landing documented in the prior research |
| Action | Check which DXVK/vkd3d-cachyos versions inside `proton-cachyos-slr` select it (or honor `VK_PRESENT_MODE_*` config); enable per game; measure frame-time + present-to-photon delta with MangoHud and the bounded capture |

### G2 — Proton latency sleep per game (zero build)

| | |
| --- | --- |
| Mechanism | `PROTON_DXVK_LOWLATENCY=1 %command%` / `PROTON_VKD3D_LOWLATENCY=1`; the runner's built-in layers implement Reflex-style late-submission pacing |
| Prize | 2,000,000–18,000,000 ns input-to-photon on GPU-bound titles (external LDAT study); near-zero on CPU-bound |
| Evidence | Flags verified present in the installed runner; farnoy LDAT study; not yet measured here |
| Action | Per-game A/B with MangoHud frame-time percentiles + bounded capture; compose with G1 |

### G3 — tearing where it matters (zero build)

`AllowTearing` defaults true; the game must request async present. For
esports titles run uncapped + async: bypasses the entire queue discipline,
prize equals current frame interval minus render time (at 240 Hz VRR, up to
~4,166,389 ns). Visual tradeoff accepted by competitive players only.

### G4 — gamescope: skip

Gamescope inserts another compositor between the game and KWin. It cannot
beat direct scanout to KWin and adds a scheduling hop. Keep installed for
compatibility, not latency.

### G5 — commit-timing-v1 client side (after C4)

`wp_commit_timing_v1` lets clients present exactly at target vblank. Combined
with KWin-side implementation (C4) this is the structural answer to
"compositor deadline vs client readiness".

## 4. Compositor path (KWin patches beyond revision 23)

### C1 — Direct scanout live discrimination (staged, ready)

One logout, three states, protocol in
`DIRECT_SCANOUT_NVIDIA_INVESTIGATION_2026-08-23.md` §5. Removes the measured
291,623 ns p50 / 1,545,012 ns p95 DP-2 render stage for every fullscreen
game on the HDR output.

### C2 — RenderJournal variance-floor defect

`RenderJournal` max-tracks variance and never decays below the last positive
excursion; one slow window inflates every window's start deadline on that
output indefinitely. Fix: symmetric EWMA decay or percentile tracking.
Prize: removes persistent early-wake inflation measured in tens to hundreds
of microseconds per frame after any transient.

### C3 — DRM safety-margin decay asymmetry

Full lateness applied immediately, surplus removed at 1/10 per frame: one
late commit costs ~ten frames of margin. Fix: faster decay when commits run
early, bounded. Prize: same magnitude class as C2 on the commit side
(commit-thread margin feeds the armed deadline directly).

### C4 — `wp_commit_timing_v1`

KWin does not implement it; eleven other compositors do. Largest structural
upstream lever: moves submission deadlines from compositor-guessed to
client-expressed. Story-sized project; pairs with G5 and
`VK_EXT_present_timing`.

### C5 — Frame-pacing deadline hints

Design already critiqued in `FRAME_PACING_CRITIQUE_AND_DESIGN_2026-08-10.md`;
revisit after C4 lands so the two mechanisms do not fight.

## 5. Browser path

### W1 — Kill XWayland from the browser loop (zero build)

Chrome runs as Flatpak; verify it launches with Ozone/Wayland
(`--ozone-platform-hint=auto`) rather than through XWayland. The prior
research attributes ~3.13 ms per interaction to the XWayland round trip.
Firefox is native Wayland by default on this stack. Chromium native is
available if Flatpak sandboxing blocks flags.
Prize: ~3,130,000 ns of input-to-display latency on every browser
interaction, the single largest browser lever.

### W2 — Browser frame alignment

Browsers vsync to the compositor; once the adaptive wake reserve and (later)
direct scanout for windowed content mature, browser scroll/paint inherits
those wins for free. No browser-side patch recommended yet; measure first.

## 6. Kernel / system path

### K1 — sched_ext A/B (installed, disabled)

Run `scx_flash` (low-overhead, latency-oriented) or `scx_lavd`
(latency-criticality aware) against the default scheduler for one week each:
desktop mix plus one stable game scene. Measure with this project's own
telemetry: wake lateness p50/p95/p99, input event age tails, DRM callback
tails. Honest expectation: microsecond-scale jitter reduction, not
milliseconds; but jitter tails set the adaptive margins, so tail wins
compound into earlier safe wakes. Rollback is `scx_switch_all` off /
reboot-free.

### K2 — GPU clock ramp behavior

GPU observed at P2 during light activity. If frames after idle show elevated
first-frame times (clock ramp), quantify ramp delay from MangoHud frame-time
traces; a persistent-performance profile trades watts for removing ramp
spikes of potentially several milliseconds. Measure before changing anything.

### K3 — Audio quantum (only if monitoring)

PipeWire runs the default graph. Audio buffering affects sound latency, not
visual input-to-photon. Only force a smaller quantum if you monitor through
the GoXLR chain while playing rhythm-type games; see
`GOXLR_AUDIO_EFFICIENCY.md` for the cost model.

## 7. Rendering quality / HDR polish

### Q1 — Real tone mapping in the TMO stage (after C1)

Once direct scanout is trusted, the currently-neutral TMO LUT stage can carry
per-output tone mapping for HDR games, replacing shader-pass tonemapping and
improving both quality and GPU cost.

### Q2 — ICtCp-quality gamut mapping

The Full pipeline's ICtCp matrices enable perceptual-domain gamut mapping;
today's path maps gamut in a linear matrix. Quality project, gated on C1.

### Q3 — SDR accuracy choice, made explicit

SDR gamut wideness 100% stretches sRGB content over panel-native primaries:
more saturated, less accurate. Setting it to sRGB improves color accuracy for
SDR games/browsers at the cost of punch. This is a preference with a real
tradeoff, not a defect; decide per taste and keep it constant across A/B
measurements.

### Q4 — Night Light × scanout validation

Night Light factors flow through the plane pipeline compensation (harness
measures them separately). After C1, re-run the color grid with Night Light
active as part of acceptance.

## 8. Validation order and gates

1. G1/G2/W1/K1 need no logout and no rebuild: measure each with MangoHud +
   `kwin-latencyctl trace repeatable-game-scene`, stock-policy control run
   alongside.
2. C1 live discrimination test (one logout).
3. C2/C3 as patch pair behind the existing gate; harness-style offline tests
   first, then capture-window A/B.
4. C4 upstream-sized effort, scheduled after 2–3 land.
5. The Tier-1 input-to-photon rig remains the gate for claiming end-user
   wins; every claim above is compositor-stage-local until it exists.

## 9. Skip list (unchanged from prior research, reconfirmed)

- `isolcpus`/`nohz_full`: costs a core for ~18 µs jitter on a gaming desktop.
- `SCHED_DEADLINE` for the compositor: blocked three ways, unshipped anywhere.
- Lock-free input queues: ~15 ns/event, noise.
- USB IRQ affinity pinning folklore: no Linux measurements found.
- gamescope as a latency tool: adds a compositor, does not remove one.
