#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check collection metadata and local documentation without downloading source."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
KWIN = ROOT / "compositor/kwin/v6.7.5"
# Apply-based builds report a version ending in -exp; KWin uses its package description.
IDENTITY = "identify-experimental-build.patch"


def safe_path(value):
    path = Path(value)
    return bool(value) and not path.is_absolute() and not any(
        part in {"..", ".git"} for part in path.parts
    ) and not any(character.isspace() for character in value)


def main():
    errors = []
    patch_count = 0
    sets = sorted({p.parent for p in ROOT.rglob("series")})
    if not sets:
        errors.append("no patch sets found")
    for directory in sets:
        label = directory.relative_to(ROOT)
        targets, created = set(), set()
        patches = sorted(directory.glob("*.patch"))
        patch_count += len(patches)
        for patch in patches:
            result = subprocess.run(
                ["git", "apply", "--numstat", "--", str(patch)],
                cwd=ROOT, text=True, capture_output=True,
            )
            if result.returncode or not result.stdout.strip():
                errors.append(f"{patch.relative_to(ROOT)}: invalid or empty diff")
                continue
            for row in result.stdout.splitlines():
                path = row.split("\t", 2)[-1]
                if not safe_path(path):
                    errors.append(f"{label}: unsupported diff path {path}")
                targets.add(path)
            created.update(re.findall(
                r"^--- /dev/null\n\+\+\+ b/(.+)$", patch.read_text(), re.M,
            ))
        try:
            metadata = json.loads((directory / "base.json").read_text())
            if "commit" in metadata:
                assert re.fullmatch(r"[0-9a-f]{40}", metadata["commit"])
                assert urlsplit(metadata["repository"]).scheme == "https"
            else:
                assert re.fullmatch(r"[0-9a-f]{64}", metadata["archive_sha256"])
                assert urlsplit(metadata["archive"]).scheme == "https"
            hashes = {}
            for line in (directory / "base.sha256").read_text().splitlines():
                if not line or line.startswith("#"):
                    continue
                digest, path = line.split("  ", 1)
                assert re.fullmatch(r"[0-9a-f]{64}", digest) and safe_path(path)
                assert path not in hashes
                hashes[path] = digest
            assert set(hashes) == targets - created, "base hashes do not cover pristine touched files"
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
            errors.append(f"{label}: invalid base metadata: {exc}")
        for series in sorted(directory.glob("series*")):
            if not series.is_file():
                continue
            names = [line for line in series.read_text().splitlines()
                     if line and not line.startswith("#")]
            if not names or len(names) != len(set(names)) or names != sorted(names):
                errors.append(f"{series.relative_to(ROOT)}: empty, duplicate or unordered series")
            for name in names:
                if Path(name).name != name or not name.endswith(".patch") or not (directory / name).is_file():
                    errors.append(f"{series.relative_to(ROOT)}: missing or invalid patch {name}")
            if directory != KWIN / "patches" and names and not names[-1].endswith(IDENTITY):
                errors.append(f"{series.relative_to(ROOT)}: must end with the {IDENTITY}")

    for kernel in sorted((ROOT / "kernel/sched-ext").glob("cachyos-*")):
        default = [line for line in (kernel / "series").read_text().splitlines()
                   if line and not line.startswith("#")]
        if {"0003-sched-wake-signals.patch", "0004-sched-ext-lean-idle-claim.patch"} & set(default):
            errors.append(f"{kernel.relative_to(ROOT)}: known-warning/unbooted kernel work "
                          "must remain outside the default series")

    bundle = KWIN
    recipe = subprocess.run(
        ["bash", "-c", 'startdir=$1; source "$1/PKGBUILD"; '
         'for i in "${!source[@]}"; do '
         'printf "%s\\t%s\\n" "${source[$i]}" "${sha256sums[$i]}"; done',
         "_", str(bundle)], text=True, capture_output=True,
    )
    if recipe.returncode:
        errors.append("KWin recipe could not be read")
    else:
        for row in recipe.stdout.splitlines():
            try:
                uri, digest = row.split("\t", 1)
                if not uri.startswith("file://"):
                    continue
                path = Path(uri[7:])
                assert path.resolve().is_relative_to(bundle) and path.is_file()
                assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
            except (ValueError, AssertionError, OSError):
                errors.append(f"KWin package input missing or hash mismatch: {row}")

    for document in sorted(ROOT.rglob("*.md")):
        if ".git" in document.parts or "artifacts" in document.relative_to(ROOT).parts:
            continue
        text = re.sub(r"```.*?```", "", document.read_text(), flags=re.S)
        for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", text):
            target = target.strip().strip("<>")
            if urlsplit(target).scheme or target.startswith("#"):
                continue
            path = unquote(target.split("#", 1)[0])
            resolved = (document.parent / path).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                errors.append(f"{document.relative_to(ROOT)}: broken local link {target}")
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix not in {".md", ".patch", ".sh", ".py", ".json", ".yml"}:
            continue
        if "artifacts" in path.relative_to(ROOT).parts:
            continue
        text = path.read_text()
        if ("https://" + "github.com/RitzDaCat/linux-interactive-latency") in text or ("/code/" + "session_") in text:
            errors.append(f"{path.relative_to(ROOT)}: private development/session link")
    stale = subprocess.run([sys.executable, str(ROOT / "scripts/index.py"), "--check"],
                           capture_output=True, text=True)
    if stale.returncode:
        errors.append("index.json is stale: run scripts/index.py")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Validated {len(sets)} patch sets / {patch_count} patches, base metadata and local documentation links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
