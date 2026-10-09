# Testing

## Before you start

- **Kernel:** keep your stock kernel installed and in the boot menu. Boot it
  once to make sure it works before you install the patched one.
- **Userspace (KWin, audio, tools):** keep the stock package in your package
  cache so you can reinstall it offline.
- Give the patched build its own name (kernel `LOCALVERSION`, package
  identity or recorded build hash), so you can verify what you are running.
  Use the bundled KWin recipe's version policy rather than inventing a `pkgrel`
  that prevents normal distribution upgrades.
- Read the patch set's compatibility table. A successful build does not prove
  that its consumer exists or that the feature activated.

## Testing fairly

- Change one thing at a time. Same game, same scene, same settings, same boot
  state for both runs.
- Define A and B precisely before starting. To isolate a kernel change, keep
  the same scheduler build and options in both arms. Comparing a new scheduler
  against another scheduler answers a different question.
- Warm up the game and shader cache first. Keep resolution, frame cap, VRR,
  compositor state, power settings and background workload the same.
- Use repeated A, B, B, A blocks or a recorded randomized order. This helps
  balance gradual drift such as heat; it does not remove all variability.
- Where a patch has an off switch (listed in its README), compare on and off
  within the same boot, and verify its reported state in both arms. Include a
  real stock-source control where the off switch leaves other patched code active.
- One run is not a result. Repeat until the difference is larger than the
  run-to-run spread.
- Record a primary metric before looking at results, retain every valid run,
  and report exclusions with reasons. Compare paired runs and their spread;
  do not treat thousands of correlated frames as independent experiments.
- Kernel callback savings, compositor timing and game frame times are separate
  outcomes. Input-to-photon claims need a physical measurement.

## Reporting

Use the **Test result** issue form for gains, no difference, regressions and
application/build-only results. Use **Bug / regression** for failures. Include:

- this collection's commit (`git rev-parse HEAD`), patch set, selected `series`,
  patch filenames, and any local changes;
- upstream source tag/commit, compiler, build command and active package or
  kernel identity;
- `uname -r` and your distribution;
- CPU, GPU and driver version;
- scheduler version/build hash and arguments, desktop/session, refresh rate,
  VRR/frame cap, game/Proton versions, and the feature's active/off evidence;
- what you ran and how you measured it (tool, duration, number of runs);
- the numbers for both arms, or the crash log (`journalctl -b -1 -k` for a
  kernel crash from the previous boot).

For gaming comparisons, attach the original frame-time logs and per-run
summaries when possible. Report average FPS, 1% and 0.1% lows, and representative
central and tail frame times (p95, p99 and maximum), with units. Report small
latency changes in nanoseconds when the tool supports that resolution, alongside
percentages. Describe stutters, crashes, audio faults and other regressions even
if the primary metric improves. If a metric was not measured, say so.

Review attached logs for personal information before posting them publicly.

"No difference" is useful evidence. Reports are reviewed before being linked
from a patch set's **Tested on** table; missing provenance or raw data stays
explicitly marked. Positive reports support further investigation, not automatic
upstream acceptance. See [CONTRIBUTING.md](CONTRIBUTING.md#upstream-evidence).

## Going back

- **Kernel:** pick the stock kernel in the boot menu, then uninstall the
  patched one.
- **Userspace:** reinstall the stock package from your cache
  (`pacman -U /var/cache/pacman/pkg/<package>.pkg.tar.zst` on Arch).
