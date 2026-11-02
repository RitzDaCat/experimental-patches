# GoXLR sampler capture efficiency candidate

Status: source-verified candidate, not installed on the host.

## Finding

GoXLR Utility 1.2.4 opens the PulseAudio/PipeWire `Line5` source immediately
when the daemon starts. This is intentional: the sampler maintains at least 30
ms of pre-record audio so a sample includes sound from before the hardware
button notification reaches userspace.

On Linux, the recorder asks Pulse for a 1024-byte maximum buffer and minimum
fragment. The live PipeWire stream is stereo float32 at 48 kHz with a 1024-byte
fragment, so each read returns 256 samples or 128 stereo frames. The original
code creates an empty `Vec<f32>`, pushes all 256 converted samples into it, hands
the allocation to the sampler ring, and drops it on every read. The same trait
also copies CPAL's existing fixed read buffer into a new vector.

This is background allocation and copying, not required audio latency.

## Candidate

[`audio-reuse-input-read-buffers.patch`](../../../../audio/goxlr-utility/v1.2.4/0001-audio-reuse-input-read-buffers.patch)
changes `AudioInput::read()` to return a slice borrowed from the input object.
Pulse conversion reuses a fixed 256-sample array, while CPAL returns its
existing fixed buffer directly.

The patch changes no:

- PipeWire or Pulse quantum;
- fragment size;
- realtime priority or affinity;
- sampler pre-record duration;
- device routing; or
- audio sample format.

It therefore targets allocator/copy overhead without making background audio
more important than game input or presentation.

## Proof and remaining gate

The patch applies to upstream tag `v1.2.4`, commit
`0c093b4c9bfb59d3426357c008760ad6620f97ae`, and passes:

```bash
cargo fmt --all -- --check
cargo check -p goxlr-audio
```

It has not been packaged, installed, or live-tested. Before installation it
needs an Arch package recipe, a sampler record/playback functional test, and
the same fixed 10-second trace before and after. Acceptance requires fewer
GoXLR/PipeWire CPU milliseconds with zero new audio faults and no KWin/input
tail regression.
