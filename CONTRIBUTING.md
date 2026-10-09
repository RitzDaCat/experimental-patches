# Contributing

Test results are the main contribution this collection needs. Follow
[TESTING.md](TESTING.md) and use the issue forms. Gains, unchanged results,
regressions and build failures all matter.

## Refreshing a patch set

Develop in a source tree for the matching public upstream. Export the source
changes into this collection; do not require testers to access a private fork.

For each update:

- Record the exact upstream source commit or archive checksum in `base.json`.
- Regenerate patches from that source with Git and refresh `base.sha256` from
  pristine touched files. Do not generate base hashes from a patched tree.
- Keep default `series` order explicit. Put known-failing or unbooted work
  outside the default path and explain how far it was tested.
- Include any consumer code, comparison switch and required install/rollback
  tools. Document their baseline and current limitations.
- Update compatibility, known issues, evidence dates and license/author notices.
- Check the whole series against fresh matching source and verify its resulting
  files. A compile, boot, daily-use claim and measured gain are distinct gates.

Use a new version directory when the source base changes. Preserve earlier
published revisions through Git history.

## Validation

From the collection's root:

```bash
bash -n scripts/apply.sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
cd compositor/kwin/v6.7.5
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 scripts/generate_readme_graphs.py --check
```

Metadata and fixture tests do not build, boot, install or measure the patches.
KWin's `bin/kwin-latencyctl test --source-only` additionally verifies the source
series and 35-file overlay using the hash-pinned public release archive. It may
download that archive temporarily if it is not already available locally.
`bin/kwin-latencyctl test` also requires a locally built candidate package.

## Upstream evidence

Keep the upstream proposal focused on one mechanism:

1. Explain the concrete problem and the changed code path, with source identity.
2. Include a minimal patch against the upstream version being reviewed, preserving
   upstream attribution for backports.
3. Link reproducible A/B instructions and raw data from independent testers.
4. Report central and tail outcomes, spread or uncertainty, stability, null results
   and regressions. Separate microbenchmarks from game and physical latency tests.
5. Explain compatibility, resource cost, fallback behavior and remaining issues.
6. Follow that upstream's license, review, testing and sign-off requirements.

Community reports help establish where a change works and where it does not.
They supplement correctness review and maintainers' judgment.
