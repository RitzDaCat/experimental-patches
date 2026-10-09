# Staging this repo for testers: opt-in, toggleable, and hard to get stuck in

> **Status 2026-08-11:** changes 1 and 2 shipped in revision 22
> (`patches/0020-runtime-optin-latency-policy.patch`): the policy defaults off
> and reloads live from the `[LatencyExperiment]` group in `kwinrc`. Change 4
> shipped in `kwin-latencyctl status`. Change 3 (one-shot arming) is not
> implemented; default-off plus live disable removes the failure it targeted
> for policy state, so only a package that cannot start still needs the cached
> rollback path. Change 5 is in the README recovery section.

Facts below come from `reference/patched-overlay/src/core/renderloop.cpp`,
`bin/kwin-latencyctl`, `install.sh`, and
`reference/upstream/kwin-6.7.4/src/dbusinterface.h`, read on 2026-08-10.

## 1. The master switch already exists

Every feature static in `renderloop.cpp:47-60` is written as
`s_experimentKernelAllowed && ...` or ternaries on the same flag:

```cpp
static const bool s_experimentKernelAllowed = experimentKernelAllowed();
static const int s_schedulerMarginMode = s_experimentKernelAllowed ? ... : 0;
static const int s_renderBudgetMode    = s_experimentKernelAllowed ? ... : 0;
static const bool s_vrrRepaintCoalescing = s_experimentKernelAllowed && ...;
```

One false there zeroes the whole series. So the off switch is already built and
already proven; it is simply spelled badly. Today a tester turns everything off
by setting `KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE` to a string that is not
their kernel. That works, and nobody will ever guess it.

The work is not adding a switch. It is renaming the one that exists and
flipping which way it points.

## 2. Change one: invert the default

Revision 20 deliberately made the policy compiled-in and always-on behind the
baked kernel release. For a personal machine that was right. For a tester
distribution it is the opposite of what is wanted, because it means installing
the package *is* enabling the experiment.

Proposal: add a single opt-in variable, default off.

```cpp
static const bool s_experimentOptIn =
    environmentVariableIntValue("KWIN_LATENCY_EXPERIMENT").value_or(0) == 1;
static const bool s_experimentEnabled = s_experimentOptIn && experimentKernelAllowed();
```

The baked kernel release stays, but it changes role: it is no longer the
enable, it is the safety AND-condition. A tester on a different kernel still
fails closed to stock.

What this buys, in one sentence: installing the package changes nothing until
the tester asks for it, so the entire failure class "I installed it and my
desktop broke" disappears.

Every existing variable keeps working underneath the master flag, so the
per-feature control the project already documents is unchanged.

## 3. Change two: make the toggle work without a restart

This is the single highest-value anti-stuck item, and it is the same work
scoped in `docs/LOW_LATENCY_LAYER_COMPARISON_2026-08-10.md` section 5a.

Today the five values are `static const`, read once at library load. A tester
whose session went wrong must edit a file, log out, and log back in — which is
exactly the moment they are least able to, because the thing that is wrong is
the compositor.

KWin already ships the trigger. `org.kde.KWin.reconfigure` is a scriptable
D-Bus method (`dbusinterface.h:57`) whose body is
`Workspace::self()->reconfigure()` (`dbusinterface.cpp:64-67`). Moving the five
statics into a settings object refreshed on that signal means a bad policy is
undone inside the live session, with no logout and no reboot.

The environment variables stay as the boot-time defaults, so nothing already
written breaks.

## 4. Change three: arm anything that still needs a restart

For whatever cannot be made live, borrow the display-settings pattern. Write
the profile with a one-shot marker; if the next session does not confirm the
policy is good, the marker expires and the profile is removed. A tester who
locks themselves out gets a stock session on the following boot without
touching a TTY.

This matters because `environment.d` persists. Without arming, a policy that
breaks login breaks *every* subsequent login too.

## 5. What already protects testers, and should be kept

`install.sh` is ahead of most projects here. Its preflight refuses to proceed
unless:

1. a signed stock `kwin` package is in `/var/cache/pacman/pkg`, because "a
   compositor that will not start is exactly when you cannot download one";
2. `checkupdates` is present and reports no pending kernel update, since a
   reboot into a different kernel silently disables the gate.

`kwin-latencyctl` also backs up the profile before every write
(`backup_profile`, line 214) into `artifacts/results/profile-backups/`, and
`rollback` and `remove` both run `sudo pacman -S kwin`.

Keep all of it. Add one thing: a printed TTY recovery path in the README, since
a tester who has lost their session cannot read a doc in a browser.

## 6. The honest cost of defaulting off

Most testers will report stock numbers by accident. A default-off build means
"I installed it and saw no difference" becomes the most common report, and it
will be indistinguishable from "the patches do not work" unless the tooling
makes state unmissable.

Two mitigations, both cheap:

- `status` must state the active policy in one unambiguous line, not leave it
  to be inferred.
- Every capture summary must record the policy state in the file itself, so a
  mislabelled report is detectable after the fact rather than trusted.

This cost is worth paying. A tester who reports a stock number is recoverable;
a tester whose desktop will not start is lost, and tells ten other people.

## 7. Recommended order

| Step | Change | Removes |
| --- | --- | --- |
| 1 | Master opt-in flag, default off | Install-breaks-desktop entirely |
| 2 | Live reload on `reconfigure` | Logout required to recover |
| 3 | One-shot arming for restart-only settings | Persistent bad profile |
| 4 | State in `status` and in capture summaries | Silently mislabelled reports |
| 5 | TTY recovery in README | Tester with no session and no instructions |

Steps 1 and 5 are small and independent; they can ship before the rest. Step 2
is the real engineering, and it is the same work the per-game toggle needs, so
it should be built once and used by both.

## 8. What this does not solve

A patched compositor that segfaults at startup still costs the tester a
session. Default-off narrows that to "the package itself is broken" rather than
"the policy is wrong", which is a much smaller and much more testable surface,
but it does not reach zero. The cached rollback package and the TTY path remain
the floor, and both need to be documented rather than assumed.
