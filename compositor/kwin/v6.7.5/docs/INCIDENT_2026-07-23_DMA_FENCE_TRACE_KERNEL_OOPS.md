# Kernel `dma_fence` trace incident on 2026-07-23

## Outcome

An ad-hoc `perf record` probe enabled the DRM vblank and `dma_fence` tracepoint
families on the live KDE Wayland session. At 13:26:46 CDT, KWin performed a DRM
sync-object transfer and the active fence trace handler dereferenced a null
pointer in kernel context. KWin exited, the collector became stuck in
uninterruptible sleep, and the machine later required a forced restart.

This command was run manually during revision 15 diagnostic development. It was
not part of `kwin-latencyctl`, `capture_pipeline_window.sh`, a package patch, or
an installed service.

## Exact fault boundary

The previous-boot journal recorded:

```text
BUG: kernel NULL pointer dereference, address: 0000000000000000
CPU: 12 PID: 1079 Comm: kwin_wayland
RIP: trace_event_get_offsets_dma_fence+0x15/0xb0
perf_trace_dma_fence+0x66/0x1c0
__do_trace_dma_fence_signaled+0x37/0x50
dma_fence_allocate_private_stub+0x18f/0x1a0
drm_syncobj_transfer_ioctl+0x260/0x440
drm_ioctl+0x2fc/0x4b0
```

The installed `7.1.4-1-cachyos` trace-event header constructs fence records by
calling `fence->ops->get_driver_name(fence)` and
`fence->ops->get_timeline_name(fence)`. The fault occurred inside that trace
record construction while the DRM sync-object path was allocating and
signaling a private stub fence.

KWin was the task that exercised the vulnerable kernel path. Neither the KWin
page-flip handler nor revision 15 invoked `perf`, tracefs, ftrace, or a
`dma_fence` tracepoint.

## Modification audit

| Component | Live during incident | Finding |
| --- | --- | --- |
| Manual `perf record` probe | Yes | Sole component that activated the faulting kernel trace handler |
| Installed KWin revision 14 | Yes | Custom package was live, but the policy and capture environment were disabled |
| KWin `DrmGpu::pageFlipHandler` | Yes | Source is identical in the pristine and patched overlays; both extracted function bodies hash to `a9a8b9420924f3dbc024ba2e7e3f09171fa502434c4ceadbb7192d4f9b974b19` |
| Revision 15 patch | No | Staged source only; it had not built or installed |
| Revision 15 exact-frame capture | No | Uses KWin `steady_clock` timestamps and bounded file output; it does not access perf events or tracefs |
| `capture_pipeline_window.sh` | No | Uses KWin files, `/proc`, interrupts, journals, and post-window device queries; it did not contain a kernel collector |
| DRM color-state probe | No | Reads client-visible DRM plane properties and blobs on its own file descriptor; it does not submit an atomic display commit or activate tracepoints |

At the time of the incident, the installed revision 14 binary and library also
matched the tracked revision-14 package byte-for-byte. The release manifest
remained pinned to revision 14 while `PKGBUILD` staged revision-15 source.
Revision 15 was promoted only after the trace prohibition and preflight were
added, a clean package was built, its shipped library was inspected, and the
full lifecycle verifier passed. Revision 14 remains archived as the incident
baseline; it is still the package running on the machine until the owner
explicitly installs revision 15.

## Separate post-reboot symptom

The forced restart left an unclean session and XFS journal recovery. During the
next login, the first KWin process crashed in the upstream-identical
`DrmGpu::pageFlipHandler`. The wrapper restarted KWin one second later, but
`ksplashqml` and `kcminit` had already lost their Wayland connection. The splash
remained for 31.225 seconds before exiting. This explains the slow Plasma
startup, but it is separate from the kernel trace-handler fault.

## Permanent project safety rule

The project does not use live kernel GPU tracepoints. In particular, do not
activate any event in the `dma_fence` trace subsystem using `perf`, tracefs,
ftrace, BPF, or another collector.

The supported measurement path is:

- exact-kernel-gated KWin in-process timing and reason telemetry;
- KWin's DRM commit-thread queue, IOCTL, and page-flip callback timestamps;
- `/proc/<pid>/task/<tid>/schedstat` deltas;
- interrupt, journal, GPU, and PipeWire snapshots outside the precision window;
- external high-speed-camera or latency-device measurement for physical
  scanout and photon timing.

Before every bounded capture, `scripts/check_trace_safety.sh` checks readable
tracefs state and running `perf` command lines. Capture aborts if it detects
active fence tracing. Repository tests also reject kernel-collector commands in
runtime entrypoints.

## Re-enablement gate

Fence tracepoints may only be reconsidered after all of the following:

1. the exact kernel fault is fixed in the kernel source used for the test;
2. the fix is verified with an isolated non-graphical DRM sync-object
   reproducer;
3. the test runs on a disposable or recovery-safe kernel;
4. no desktop compositor, game, or user session is used as the first probe;
5. the trace is proven to terminate cleanly before it is added to project
   tooling.

Until those gates pass, the prohibition is unconditional and exposes no user
toggle.
