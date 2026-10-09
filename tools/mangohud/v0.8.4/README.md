# MangoHud — v0.8.4

Two fixes for [MangoHud](https://github.com/flightlessmango/MangoHud)'s
control socket, which the upstream `mangohud-control` client uses to talk to a running game's
overlay (toggle it, start and stop logging and so on).

| # | Patch | In short | Status |
| --- | --- | --- | --- |
| 1 | [os_socket CLOEXEC](0001-os_socket-set-CLOEXEC-and-stop-leaking-fds.patch) | Child processes no longer inherit the socket; no fd leak on a failed bind | Fixes a leak seen with World of Warcraft |
| 2 | [shared control socket](0002-control-share-one-listening-socket-across-Vulkan-ins.patch) | One socket per game, shared by all its Vulkan instances | Fixes the control socket not answering in World of Warcraft |

## Before you start

- **Base:** upstream tag `v0.8.4` (`992103e4fb744897826de04ea00a2f71e7018214`). Exported with `git format-patch` from the
  author's `control-socket-fixes` branch; each patch's commit message has the
  full detail.
- **Apply:** `scripts/apply.sh tools/mangohud/v0.8.4 /path/to/MangoHud`
- Only matters if you use the control socket (`control=` in your MangoHud
  config).
- **License:** MIT; [upstream license](LICENSE) and [Intel notices](NOTICE).

Use the [upstream v0.8.4 build instructions](https://github.com/flightlessmango/MangoHud/tree/v0.8.4#installation---build-from-source)
after applying the series. Enable the `mangohudctl` Meson build option to install
the `mangohud-control` client. Restart the test game after installing the layer so it loads
the new build; record the layer version and which control client you used.

## Tested on

Newest first. Tester results get a row here too.

| Date | Base | How far | Machine | Result |
| --- | --- | --- | --- | --- |
| 2026-10-07 | v0.8.4 tag | Applies | — | Both patches apply cleanly |
| 2026-08-03 → now | v0.8.4 | Daily use | Ryzen 7 9800X3D, RTX 4090 (NVIDIA 615.71.09) | Installed as the system Vulkan layer, inside a larger build of the author's branch (`v0.8.4-9-gd8a0e45`) |

---

## 1. Set CLOEXEC on the control socket

**What it changes.** The listening socket and each accepted client
connection are created close-on-exec (`SOCK_CLOEXEC`, `accept4`). When binding
the socket fails, it is now closed instead of leaked.

**Why.** Without close-on-exec, every program the game starts inherits the
listening socket. With World of Warcraft, `WowVoiceProxy.exe` was seen holding
it, keeping the socket alive in a process that can never answer it. A failed
bind, which is common when a game creates more than one Vulkan instance, leaked
one file descriptor for the life of the game.

**Expected result.** Child processes no longer hold MangoHud's socket, and no
descriptors leak. Nothing visible changes in the overlay.

**How to test.** With the game running, `ls -l /proc/<child pid>/fd` for a
child process (such as `WowVoiceProxy.exe`) no longer shows the
`@mangohud-<pid>` socket.

## 2. Share one control socket across Vulkan instances

**What it changes.** The control socket is opened once per process, and every
Vulkan instance uses that same socket. Closing an instance no longer closes
it; it is released when the game exits. Each accepted client connection is
still per instance, and is now closed with it.

**Why.** Some games create a short-lived Vulkan instance first, only to list
GPUs (vkd3d-proton does this; seen with World of Warcraft). That first instance
took the socket name and never drew a frame, so nobody answered on it. The
instance that actually draws then failed to bind with "address in use" and had
no socket at all. Clients connected, were never answered, and timed out.

**Expected result.** The control socket works in games that create an extra
Vulkan instance before the real one.

**How to test.** In World of Warcraft (or another vkd3d-proton game) with
`control=mangohud-%p` set, `mangohud-control -s mangohud-<game pid> toggle-hud`
should hide the overlay instead of timing out.
