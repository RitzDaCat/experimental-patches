# goxlr-utility — v1.2.4

A patch, plus an identity patch, for [goxlr-utility](https://github.com/GoXLR-on-Linux/goxlr-utility),
the Linux daemon for TC-Helicon GoXLR mixers.

| # | Patch | In short | Status |
| --- | --- | --- | --- |
| 1 | [audio-reuse-input-read-buffers](0001-audio-reuse-input-read-buffers.patch) | Stop allocating a new buffer on every sampler read | Builds; not installed or live-tested |
| 2 | [identify-experimental-build](0002-identify-experimental-build.patch) | Daemon version ends in `-exp` | Builds; `--version` prints `1.2.4-exp` |

## Before you start

- **Base:** upstream tag `v1.2.4` (`0c093b4c9bfb59d3426357c008760ad6620f97ae`).
- **Source:** the complete patch is included here; no private repository is needed.
- **License:** MIT, with the [upstream notice](LICENSE) retained.
- **Apply:** `scripts/apply.sh audio/goxlr-utility/v1.2.4 /path/to/goxlr-utility`
- **Verify:** `goxlr-daemon --version` prints `goxlr-daemon 1.2.4-exp`.
- Keep your current goxlr-utility package so you can reinstall it.

Check out the matching public source tag, check and apply this patch, then
follow the [upstream build guide](https://github.com/GoXLR-on-Linux/goxlr-utility/tree/v1.2.4)
to build/package it for your distribution. `cargo check -p goxlr-audio` alone
does not produce an installed daemon. Record the packaged daemon's identity and
restart it through your distribution's service workflow before testing audio.

## Tested on

Newest first. Tester results get a row here too.

| Date | Base | How far | Machine | Result |
| --- | --- | --- | --- | --- |
| 2026-10-09 | v1.2.4 tag | Compiles | — | Patches 1–2 apply; debug build of `goxlr-daemon` prints `goxlr-daemon 1.2.4-exp`. Not installed or run |
| 2026-10-07 | v1.2.4 tag | Applies | — | Applies cleanly |
| 2026-08-10 | v1.2.4 tag | Compiles | — | `cargo fmt --check` and `cargo check -p goxlr-audio` pass. Not packaged or run |

---

## 1. Reuse input read buffers

**What it changes.** The sampler's audio input `read()` now returns a view of
a buffer it keeps, instead of a newly allocated copy. The PulseAudio path
converts into a fixed 256-sample array that is reused; the CPAL path hands
back its existing read buffer directly.

**Why.** The daemon records from the GoXLR's sampler input all the time it
runs, so a sample can include about 30 ms of sound from before you pressed the
button. On PipeWire each read returns 256 samples, about every 2.7 ms. The
stock code builds a new vector for every read, copies the samples in, hands it
over and frees it: roughly 370 allocations a second, forever, for audio that
is usually thrown away.

**Expected result.** Slightly less CPU time for the GoXLR daemon, with
identical audio. Nothing about how audio is handled changes: not the PipeWire
quantum, fragment size, priority, routing, sample format or pre-record length.
**Not shown:** it builds (`cargo check`, `cargo fmt --check`) but has not been
packaged, installed or run.

**How to test.**

1. Record a sample on the GoXLR and play it back. It must sound the same as
   before, including the sound just before the button press.
2. Compare the daemon's CPU time over the same 10 seconds before and after,
   for example with `pidstat -p $(pidof goxlr-daemon) 10 1`.
3. Watch for new audio dropouts or crackle.

## 2. Experimental build identity

**What it changes.** Appends `-exp` to the daemon's version: the startup log
line, the `daemon_version` sent to clients and shown in the UI, and
`goxlr-daemon --version`.

**Why.** A tester must be able to tell the patched daemon from the stock one.

**Expected result.** No behaviour change; the version reads `1.2.4-exp`.

**How to test.** `goxlr-daemon --version`, or the version shown in the UI.
