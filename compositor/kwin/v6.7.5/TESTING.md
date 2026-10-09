# Testing guide

This is the complete tester path: install, verify, activate, compare, report,
and get out safely. Each step names the exact command.

## What you are testing

A patched KWin that wakes later and more precisely, so a frame carries fresher
input. No input-to-photon improvement has been measured yet; your report is
how that gap closes. A null result is data — report "no difference" as readily
as an improvement. The claims table is in
[docs/SCHEDULING_MODEL_AND_CLAIMS.md](docs/SCHEDULING_MODEL_AND_CLAIMS.md).

## Requirements

- An Arch-based system whose repository KWin is 6.7.5, with Plasma on Wayland.
- `makepkg`, Python 3, `pacman-contrib` (for `checkupdates`).
- A tested way back: the install refuses to run without a stock `kwin` package
  in the pacman cache, and stashes a copy in `artifacts/rollback/`.

## Install

Read-only checks first. Neither changes system state.

```bash
./bin/kwin-latencyctl status
./bin/kwin-latencyctl test --source-only
```

Then build and install in one pass:

```bash
./install.sh
```

Reboot afterwards. A Wayland compositor cannot be replaced in place.

Installing changes nothing by itself. The policy ships opted out, and the
compositor you reboot into behaves exactly like stock until you opt in.

## Verify before you measure

```bash
./bin/kwin-latencyctl status
```

Read two lines, every time, and again after any system update:

- `Baked gate:` must say it matches the running kernel. On a mismatch every
  patch is inert and any measurement is meaningless; rebuild with
  `./install.sh` to re-gate. A pacman hook also warns when a kernel or kwin
  update breaks this.
- `Opt-in (kwinrc):` says whether the policy is live right now.

## Activate for the whole session

```bash
./bin/kwin-latencyctl enable
```

```bash
./bin/kwin-latencyctl disable
```

Both apply live through the compositor's config watcher — no logout. `enable`
is the single reviewed policy; there are no tuning knobs to sweep.

## Activate per game from Steam

The package installs `kwin-latency-game` to `/usr/bin`. Set one game's launch
options to:

```text
kwin-latency-game -- %command%
```

The policy turns on when the title starts and the previous state returns when
it exits, crash included. In a session already opted in, `--off` forces stock
for one title instead. Two limits: a SIGKILL of the wrapper itself skips the
restore (`status` shows it, `disable` clears it), and Flatpak Steam cannot see
the wrapper — use native Steam, or prefix with `flatpak-spawn --host`.

## Run a fair comparison

1. Pick one game scene you can repeat, with a fixed FPS cap and fixed display
   settings.
2. Play it opted out, then opted in, in the same session. `enable` and
   `disable` are live, so nothing else changes between runs.
3. Do not change monitor mode, HDR, VRR, or the game's settings between runs.
4. Note what you felt before you look at any numbers. Swapping the order of
   runs between sessions guards against expectation.

Optional evidence to attach:

```bash
./bin/kwin-latencyctl snapshot mytest
```

> [!CAUTION]
> Snapshots collect USB device lists, monitor EDID data, and package state.
> Those can carry device serial numbers and your hostname. Read the files and
> remove what you do not want public before attaching them.

## Report

Open a **Test result** issue for results, good or bad. Open a **Bug / regression**
issue for anything that failed to build, install, or roll back. Both templates
ask for the `status` output; paste it unedited.

## If something breaks

Three exits, from mildest to full removal:

```bash
./bin/kwin-latencyctl disable    # stock policy values, live immediately
./bin/kwin-latencyctl rollback   # restore signed repository KWin (reboot)
./bin/kwin-latencyctl remove     # reinstall repository KWin (reboot)
```

If the desktop will not start at all: switch to a text console with
`Ctrl+Alt+F3`, log in, and run:

```bash
sudo pacman -U "$(ls -t /var/cache/pacman/pkg/kwin-[0-9]*.pkg.tar.zst | head -n 1)"
```

Then reboot. If the cache is empty, use the copy the installer stashed in the
repo's `artifacts/rollback/` directory instead.
