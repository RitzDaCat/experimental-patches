# Frame pacing: what low_latency_layer does, where it is hacky, and a better path

Sources read on 2026-08-10: a shallow clone of
`Korthos-Software/low_latency_layer` at its default branch, and
`reference/upstream/kwin-6.7.4/src/wayland/`.

## 1. The mechanism, stated plainly

Reflex-style pacing does not make frames faster. It makes them *later*. If the
game runs ahead, the frame it hands the compositor was simulated from input
sampled two or three frames ago. Holding the CPU frame back until just before
the GPU can consume it means the same photon carries fresher input. The cost is
throughput headroom; the gain is that the newest sample reaches the screen.

## 2. What the layer gets right

- **Real device timestamps.** `TimestampPool` measures actual submit-to-complete
  spans on the GPU rather than guessing from wall clock.
- **Bounded tracking.** `submission_spans` is keyed by present id with a
  `MAX_TRACKED_PRESENTS` ring and stale eviction, so an application that
  submits without presenting cannot grow it without limit.
- **Proper blocking where it matters.** `swapchain_monitor` and
  `timestamp_pool` both use `condition_variable_any`.
- **The hack is quarantined.** For a normal, coupled game `delay()` returns
  before any jitter runs:

  ```cpp
  if (!this->is_simulation_decoupled) { /* record and */ return; }
  ```

So the statistical machinery below applies to one named application, not to
every title. That is a deliberate and defensible boundary.

## 3. Where it is hacky, in order of severity

### 3a. Spin-waiting instead of sleeping to a deadline

`delay_controller.cc:27` and `:47` both wait like this:

```cpp
while (DeviceClock::now() < this->previous_frame->release + min_delay) {
    std::this_thread::yield();
}
```

This burns a core for up to a full frametime, and it competes with the game's
own worker threads on the machine where latency is being measured.
`std::this_thread::yield()` carries no deadline guarantee; under load the
scheduler decides when the thread comes back.

The correct primitive is an absolute-time sleep,
`clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, nullptr)`. This is
the same lesson patches 0001 and 0002 applied to KWin, which replaced a
`QBasicTimer` that truncated its delay to whole milliseconds with an absolute
timerfd deadline. The layer solved the game-side problem with the weaker
timing primitive.

This is the one item that is both clearly wrong and cheap to fix.

### 3b. Inferring a value nobody exposes

For the decoupled case the layer perturbs its own frametime with a jitter,
measures how frametime responds, clamps that to a gradient in [-1, 1], and
smooths it with an EWMA at `ALPHA = 0.01`:

```cpp
this->gradient_ewma = (ALPHA * gradient) + ((1.0 - ALPHA) * this->gradient_ewma);
```

Three consequences:

1. `ALPHA = 0.01` is roughly a 100-frame time constant: about 0.7 s at 144 Hz.
   Every scene change, load screen, or resolution switch pays that again.
2. `DELTA_GAIN = 5.0` with a clamp to `[0, frametime]` is a proportional
   controller with no stability analysis. It is tuned, not derived.
3. The code documents an unexplained sign inversion and works around it by
   updating only on the upside: "For some reason using the UP and DOWN gradient
   of jitter in Marvel Rivals is causing issues where the expected sign is
   inverted." An unexplained sign is a correctness risk, not a style issue.

None of this is incompetence. It is what you are forced into when the number
you need is not published by anyone.

### 3c. A per-application quirk flag

`is_simulation_decoupled` is set for Marvel Rivals specifically. Quirk tables
are the part of a project that ages worst: every new title is a bug report.

## 4. The better path, and why this repo is positioned for it

The layer is *estimating* a deadline that the compositor already *knows*.

KWin computes the next presentation time every frame. With this project's
patches it also holds a measured per-output, per-presentation-path wake reserve
and an adaptive render budget. That is exactly the quantity a game needs to
answer "when should I start simulating?".

What Wayland exposes today, checked against `kwin-6.7.4/src/wayland/`:

| Protocol | Present in KWin 6.7.4 | Direction |
| --- | --- | --- |
| `presentation-time` | yes, `presentationtime.h` | Backward: `presented()` reports refresh duration, timestamp, mode |
| `fifo_v1` | yes, `fifo_v1.h` | Ordering semantics, not a deadline |
| `commit-timing-v1` | staged in wayland-protocols; not found by `grep -rlniE "commit_timing"` over KWin `src/` | Client requests a target present time |

`commit-timing-v1` exists as a staging protocol at
`/usr/share/wayland-protocols/staging/commit-timing/commit-timing-v1.xml`. It
is client-to-compositor only: `wp_commit_timing_manager_v1.get_timer` and
`wp_commit_timer_v1.set_timestamp`, and the file declares **no events**. A
client can therefore say "apply this commit at time T", but the compositor has
no channel to say "start your frame now".

So the compositor can tell a client when a frame *was* shown, and a client can
request when one *should* be shown, but nothing tells the client when to
*start*. That missing hint is the whole problem, and no staged protocol covers
it.

### Tier 1 — fix the wait (small, independent, upstreamable)

Replace both yield loops with `clock_nanosleep(..., TIMER_ABSTIME, ...)`.
Removes the core burn and the scheduling slop. Roughly thirty lines, no
protocol work, benefits every user of the layer immediately. This belongs
upstream in their repo, not here.

### Tier 2 — publish the deadline (the real fix)

A compositor-to-client hint carrying, per surface:

- the next expected presentation time,
- the compositor's own measured cost for that output and presentation path,
- the confidence or jitter band around both.

The client then starts its frame at `present - compositorCost - ownRender -
margin`. The jitter probe, the EWMA, and the tuned gain all become
unnecessary, because the estimated term is replaced by a measured one.

### Tier 3 — what only this project can supply

The hint is only as good as its numbers. Patches 0003 through 0006 and 0009
already learn the wake reserve and render budget per output and per
presentation path, and reset them on refresh change. Publishing those values is
a smaller change than deriving them, and this repo has already done the
deriving.

## 5. Benefit, stated per tier

| Tier | Removes | Convergence | App-specific code |
| --- | --- | --- | --- |
| Today | — | ~100 frames | quirk flag needed |
| 1 | core burn, wait slop | unchanged | unchanged |
| 2 | jitter probe, EWMA, tuned gain | immediate | most cases resolved |
| 3 | remaining estimate error | immediate | reserve is measured, not guessed |

## 6. The honest limit

A deadline hint does not fix a decoupled simulation thread. If a game's
simulation runs three frames ahead regardless of render pacing, telling it when
to present changes nothing, because the thread that ignores pacing is the one
producing the stale input. The layer's own author calls this an application bug
fixable by one UE5 configuration option, and that assessment looks right.

So even the ideal design keeps a statistical fallback for decoupled titles. The
gain from Tier 2 and Tier 3 is that the fallback stops being the common path
and becomes the exception it should always have been.

## 6a. The blocking precondition

This project has never recorded a physical input-to-photon number. Its own
capture summaries say so, for example in
`artifacts/results/20260721-210202-palworld-directscanout-r11-trace/summary.md`:

> Pageflip callback timing ends at KWin's DRM callback. It is not a physical
> input-to-photon measurement.

Tier 3 publishes this project's learned wake reserve to other processes. An
error in that model is currently a local scheduling error. Published as a hint,
the same error becomes every consuming client's error, and it is harder to
detect because the client has no way to audit it. Validate the reserve against
a physical measurement before exporting it.

## 7. Where this leaves us

Nothing here needs to change in this repository yet. Tier 1 is their bug. Tier
2 is protocol work with an upstream audience. Tier 3 is the piece this project
would contribute, and it only becomes useful once Tier 2 exists to carry it.

The near-term value is the framing: this project owns the compositor half of
the deadline, and any serious frame-pacing design on Linux needs that half
published rather than inferred.
