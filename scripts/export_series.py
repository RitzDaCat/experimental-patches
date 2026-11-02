#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Export a patch set from a branch of a source fork.

The fork holds the patches as commits on top of a public base (a tag, or a
commit of a development branch). This writes the commits base..head into the
patch-set directory with git format-patch, pins the base in base.json and
base.sha256, lists every patch in series.all and refreshes the matching
compatibility target. Other series files are maintained by hand and must
only name exported patches.
"""
import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "compatibility/targets.json"
SCOPE = "SHA-256 of pristine touched files, not the entire source tree"
PATCH_NAME = re.compile(r"\d{4}-.+\.patch")
# Fixed options so the output does not depend on the caller's git config.
FORMAT_PATCH = [
    "-c", "core.abbrev=12", "-c", "diff.noprefix=false", "-c", "diff.mnemonicPrefix=false",
    "format-patch", "--quiet", "--zero-commit", "--no-signature", "--no-thread",
    "--no-cover-letter", "--no-renames", "--no-binary", "--diff-algorithm=myers",
    "--subject-prefix=PATCH",
]


def git_bytes(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise SystemExit(f"git {' '.join(args)}: {result.stderr.decode().strip()}")
    return result.stdout


def git(repo, *args):
    return git_bytes(repo, *args).decode().strip()


def resolve_base(repo, base):
    commit = git(repo, "rev-parse", "--verify", f"{base}^{{commit}}")
    tag = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", f"refs/tags/{base}"],
                         capture_output=True, check=False).returncode == 0
    return commit, base if tag else None


def touched_files(repo, base, head):
    """Hash the base copy of every changed file; list the files the series adds."""
    fields = git_bytes(repo, "diff", "--no-renames", "--name-status", "-z", base, head).decode().split("\0")
    present, absent = {}, []
    for status, path in zip(fields[0::2], fields[1::2]):
        if status == "A":
            absent.append(path)
        else:
            present[path] = blob_hash(repo, base, path)
    return present, sorted(absent)


def blob_hash(repo, commit, path):
    return hashlib.sha256(git_bytes(repo, "cat-file", "blob", f"{commit}:{path}")).hexdigest()


def write_patches(repo, base, head, directory):
    for old in directory.iterdir():
        if old.is_file() and PATCH_NAME.fullmatch(old.name):
            old.unlink()
    git(repo, *FORMAT_PATCH, "-o", str(directory), f"{base}..{head}")
    names = sorted(p.name for p in directory.iterdir() if PATCH_NAME.fullmatch(p.name))
    if not names:
        raise SystemExit(f"no commits between {base} and {head}")
    (directory / "series.all").write_text("".join(f"{n}\n" for n in names))
    return names


def check_series(directory, names):
    errors = []
    for series in sorted(directory.glob("series*")):
        for line in series.read_text().splitlines():
            if line and not line.startswith("#") and line not in names:
                errors.append(f"{series}: {line} is not an exported patch")
    if errors:
        raise SystemExit("\n".join(errors))


def update_target(target, repo, metadata, files, absent, directory, version):
    base = {k: v for k, v in metadata.items() if k != "scope"}
    # Keep extra pinned files (such as the Makefile version) from the old audit.
    extra = {name for name in target["files"] if name not in files and name not in absent}
    target.update(version=version, patch_set=str(directory.relative_to(ROOT)), status="applies", base=base)
    target["files"] = dict(sorted({**files, **{n: blob_hash(repo, base["commit"], n) for n in extra}}.items()))
    target["absent_files"] = absent
    series = target.get("series", "series")
    names = [n for n in (directory / series).read_text().splitlines() if n and not n.startswith("#")]
    target["patches"] = {n: hashlib.sha256((directory / n).read_bytes()).hexdigest() for n in names}
    for tracking in target["tracking"]:
        if tracking["kind"] == "package":
            tracking["version"] = version
        elif "tag" in base and tracking["ref"].startswith("refs/tags/"):
            tracking.update(ref=f"refs/tags/{base['tag']}", commit=base["commit"])
        elif "tag" not in base:
            tracking["commit"] = base["commit"]


def main():
    parser = argparse.ArgumentParser(description="Export a patch set from a branch of a source fork.")
    parser.add_argument("--repo", type=Path, required=True, help="source fork")
    parser.add_argument("--base", required=True, help="public base tag or commit")
    parser.add_argument("--head", required=True, help="branch or tag holding the patches")
    parser.add_argument("--target", help="compatibility target ID to refresh")
    parser.add_argument("--version", help="target and package version, e.g. 7.3.1-1")
    parser.add_argument("directory", type=Path, help="patch-set directory in this collection")
    args = parser.parse_args()
    directory = args.directory.resolve()
    in_collection = directory.is_relative_to(ROOT)
    if args.target and not (args.version and in_collection):
        raise SystemExit("--target needs --version and a patch-set directory in this collection")

    commit, tag = resolve_base(args.repo, args.base)
    head = git(args.repo, "rev-parse", "--verify", f"{args.head}^{{commit}}")
    if subprocess.run(["git", "-C", str(args.repo), "merge-base", "--is-ancestor", commit, head], check=False).returncode:
        raise SystemExit(f"{args.head} is not based on {args.base}")

    directory.mkdir(parents=True, exist_ok=True)
    names = write_patches(args.repo, commit, head, directory)
    check_series(directory, names)
    files, absent = touched_files(args.repo, commit, head)
    (directory / "base.sha256").write_text("".join(f"{h}  {p}\n" for p, h in sorted(files.items())))

    base_json = directory / "base.json"
    metadata = json.loads(base_json.read_text()) if base_json.is_file() else {}
    if "repository" not in metadata:
        raise SystemExit(f"{base_json}: add the public repository URL first")
    extra = {k: v for k, v in metadata.items() if k not in {"repository", "commit", "tag", "scope"}}
    metadata = {"repository": metadata["repository"], "commit": commit,
                **({"tag": tag} if tag else {}), **extra, "scope": SCOPE}
    base_json.write_text(json.dumps(metadata, indent=2) + "\n")

    if args.target:
        manifest = json.loads(MANIFEST.read_text())
        matches = [t for t in manifest["targets"] if t["id"] == args.target]
        if not matches:
            raise SystemExit(f"unknown target: {args.target}")
        update_target(matches[0], args.repo, metadata, files, absent, directory, args.version)
        manifest["checked_on"] = datetime.date.today().isoformat()
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")

    if in_collection:
        subprocess.run([sys.executable, str(ROOT / "scripts/index.py")], check=True)
    print(f"{directory}: {len(names)} patches on {tag or commit[:12]}")


if __name__ == "__main__":
    main()
