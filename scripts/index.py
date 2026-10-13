#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Write index.json, the machine-readable list of patch sets; --check fails if it is stale."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.json"


def natural(name):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name)]


def series_patches(path):
    return [line for line in path.read_text().splitlines()
            if line and not line.startswith("#")]


def build():
    groups = {}
    for series in sorted(ROOT.rglob("series")):
        directory = series.parent
        set_path = directory.relative_to(ROOT)
        # A set's own folder may be "patches/" under its version (KWin bundles tooling beside it).
        version_dir = set_path.parent if set_path.name == "patches" else set_path
        groups.setdefault(str(version_dir.parent), []).append((version_dir.name, directory))
    sets = []
    for component, members in sorted(groups.items()):
        members.sort(key=lambda member: natural(member[0]))
        for rank, (version, directory) in enumerate(reversed(members)):
            base = json.loads((directory / "base.json").read_text())
            base.pop("scope", None)
            entry = {
                "component": component,
                "version": version,
                "path": str(directory.relative_to(ROOT)),
                "current": rank == 0,
                "base": base,
                "series": {},
            }
            for name in sorted(directory.glob("series*")):
                key = "default" if name.name == "series" else name.name.removeprefix("series.")
                entry["series"][key] = series_patches(name)
            sets.append(entry)
    return {"schema": 1, "sets": sets}


def main():
    text = json.dumps(build(), indent=2) + "\n"
    if sys.argv[1:] == ["--check"]:
        if not INDEX.exists() or INDEX.read_text() != text:
            print("index.json is stale: run scripts/index.py", file=sys.stderr)
            return 1
        return 0
    if sys.argv[1:]:
        print("usage: scripts/index.py [--check]", file=sys.stderr)
        return 2
    INDEX.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
