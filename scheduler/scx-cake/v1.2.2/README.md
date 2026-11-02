# scx_cake 1.2.2: CachyOS release source

Identity patch for scx_cake 1.2.2 in scx-scheds 1.1.4, the current CachyOS
release checked on 2026-10-22. Source: public
[scx v1.1.4](https://github.com/sched-ext/scx/tree/v1.1.4), commit
`e7b3a219617472cf78880ac424714e52c932db61`. License: GPL-2.0-only.

The patch pairs the crate and Cargo.lock versions at `1.2.2-exp`. It changes
the build identity only. This release does not contain the native-bitops,
lean-idle or wake-signal consumers carried by the separate
[experimental nightly](../nightly/). Use the nightly for those kernel tests.

From this collection's root, with a disposable checkout of the pinned commit:

```bash
scripts/apply.sh scheduler/scx-cake/v1.2.2 /path/to/scx --check
scripts/apply.sh scheduler/scx-cake/v1.2.2 /path/to/scx
cd /path/to/scx
cargo build --locked --release -p scx_cake
./target/release/scx_cake --version
```

Expected identity: `scx_cake 1.2.2-exp`. Keep the stock package for rollback;
follow [TESTING.md](../../../TESTING.md) before activation.

| Date | Gate | Result |
| --- | --- | --- |
| 2026-10-22 | Source application | Full identity series applies with zero fuzz; parsed Cargo manifest and lockfile both report `1.2.2-exp` |

This refreshed series has not been compiled, loaded or benchmarked.
