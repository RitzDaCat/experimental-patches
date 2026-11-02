# low_latency_layer compared, and per-game toggling

> **Status 2026-08-11:** mechanism 5a shipped in revision 22. The live-reload
> path uses `KConfigWatcher` on the `[LatencyExperiment]` group in `kwinrc`
> rather than the `reconfigure()` D-Bus round trip, and the wrapper is
> `kwin-latency-game -- %command%` (installed to `/usr/bin` by the package).

Read on 2026-08-10 from a shallow clone of
`https://github.com/Korthos-Software/low_latency_layer` at its default branch.
KWin facts below come from `reference/upstream/kwin-6.7.4/` and
`reference/patched-overlay/`.

## 1. What low_latency_layer is

An implicit Vulkan layer, MIT licensed, C++23. It provides hardware-agnostic
implementations of `VK_NV_low_latency2` (Reflex) and `VK_AMD_anti_lag`, so AMD
and Intel GPUs get Reflex-style pacing without driver support. Paired with
dxvk-nvapi it serves Proton titles.

It runs **inside the game process**. Its `DelayController`
(`src/delay_controller.hh`) holds the CPU frame back so simulation cannot run
2-3 frames ahead of the GPU. It injects a small per-frame jitter, derives a
gradient, and pushes that into an EWMA to detect when the simulation queue has
reached its floor. Marvel Rivals is the named decoupled-queue case.

## 2. What this project is

Nineteen patches inside **kwin_wayland**, one process started at login. They
change when the compositor wakes and presents: absolute timerfd deadlines, a
per-output and per-presentation-path wake reserve, an adaptive render budget,
VRR cadence coalescing, and DRM/NVIDIA colour-pipeline work.

## 3. The two do not overlap

They sit on different segments of the same input-to-photon chain.

| Segment | Owner | Mechanism |
| --- | --- | --- |
| Input sampled to draw submitted | low_latency_layer | Delay the CPU frame start so queue depth falls |
| Draw submitted to GPU done | neither | Driver and hardware |
| GPU done to compositor wake | this project | Adaptive wake reserve, absolute timerfd |
| Compositor wake to page flip | this project | Render budget, VRR coalescing, direct scanout |

No shared file, symbol, or configuration key. Nothing found by grepping the
layer tree for `KWIN` or `kwin`. They compose: the layer shortens the queue the
compositor is waiting on, and the compositor stops overshooting its deadline.

Their own benchmark section states direct scanout was active on KDE Plasma 6.6
throughout testing, so their numbers already assume a compositor mostly out of
the path. That is the regime these patches target.

## 4. Why Steam launch options cannot toggle this project

The layer's `LOW_LATENCY_LAYER=1` works from Steam launch options because the
layer is loaded by the game process, and Steam launch options set environment
variables for exactly that process.

kwin_wayland is not that process. It starts at login, long before Steam, and
`kwin_wayland_wrapper` freezes its environment at that point. Every `KWIN_*`
variable in `reference/patched-overlay/src/core/renderloop.cpp:47-60` is read
into a `static const` at library load:

```cpp
static const int s_renderBudgetMode = s_experimentKernelAllowed
    ? std::clamp(environmentVariableIntValue("KWIN_ADAPTIVE_RENDER_BUDGET").value_or(2), 0, 2)
    : 0;
```

A `static const` initialised at load is read once per process lifetime. Setting
that variable in a launch option changes the game's environment, which the
compositor never reads. Even a correct session-wide value needs a full logout.

## 5. Three mechanisms that would work

### 5a. Wrapper command plus live config (recommended)

Steam launch options run an arbitrary command, not only environment
assignments. A wrapper can therefore talk to the running compositor:

```
kwin-latencyctl game -- %command%
```

The wrapper sets the aggressive policy, runs the game, and restores the
previous policy when the game exits, including on crash via a trap.

This needs the `static const` reads replaced by a small settings object that a
reconfigure signal can refresh. KWin already exposes the trigger:
`org.kde.KWin.reconfigure` is a scriptable D-Bus method
(`src/dbusinterface.h:57`) whose body is `Workspace::self()->reconfigure()`
(`src/dbusinterface.cpp:64-67`). Writing the values to `kwinrc` under a
dedicated group and reading them on reconfigure gives per-game control with no
restart.

Cost: convert five statics to members with a reload path, add a KConfig group,
add the wrapper subcommand. The environment variables stay as boot-time
defaults, so nothing already documented breaks.

### 5b. Automatic per-window policy, no toggle at all

RenderLoop does not see the active window today; `activeWindow` was not found
by grepping `renderloop.h` and `renderloop_p.h`. Workspace does, and Compositor
already mediates between them. Gating the aggressive policy on "a fullscreen
window is driving this output" would make it self-activating for every game and
inert on the desktop, with nothing for the user to set.

Cost: a plumbing change from Workspace to RenderLoop. Harder to A/B test than
5a, because you cannot hold the variable still.

### 5c. Environment only, session-wide

Keep what exists. `kwin-latencyctl esports` writes the profile and you log out.
Correct today, but it is a session-level switch, not a per-game one.

## 6. Recommendation

Build 5a. It is the only one of the three that answers the literal question,
it reuses a D-Bus method that already exists, and it keeps the environment
variables as the boot-time default path. Add 5b later as an automatic mode once
5a makes the policy switchable at runtime.

Install low_latency_layer independently. It is complementary, separately
maintained, and MIT licensed; there is no reason to vendor or reimplement it
here.
