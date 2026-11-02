#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check pinned distro/development targets without changing the supplied sources."""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "compatibility/targets.json"


def relative_path(value):
    path = Path(value)
    if not value or path.is_absolute() or any(p in {"..", ".git"} for p in path.parts):
        raise ValueError(f"unsafe relative path: {value}")
    if any(c.isspace() for c in value) or value.startswith("-"):
        raise ValueError(f"unsupported relative path: {value}")
    return path


def series_names(directory, series="series"):
    if not re.fullmatch(r"series(?:\.[a-z-]+)?", series):
        raise ValueError("invalid series name")
    names = [s for s in (directory / series).read_text().splitlines()
             if s and not s.startswith("#")]
    if not names or names != sorted(set(names)):
        raise ValueError(f"empty, duplicate or unordered series: {directory / series}")
    for name in names:
        if relative_path(name).name != name or not name.endswith(".patch"):
            raise ValueError(f"invalid patch name: {name}")
        if (directory / name).is_symlink() or not (directory / name).is_file():
            raise ValueError(f"missing patch: {name}")
    return names


def patch_paths(patch):
    paths = set(re.findall(r"^(?:--- a/|\+\+\+ b/)(.+)$", patch.read_text(), re.M))
    if not paths:
        raise ValueError(f"no diff paths: {patch}")
    for name in paths:
        relative_path(name)
    return paths


def load_manifest(path=MANIFEST):
    manifest = json.loads(path.read_text())
    if manifest["schema"] != 1:
        raise ValueError("unsupported compatibility manifest schema")
    ids = set()
    for target in manifest["targets"]:
        if not re.fullmatch(r"[a-z0-9-]+", target["id"]) or target["id"] in ids:
            raise ValueError("invalid or duplicate target ID")
        ids.add(target["id"])
        if target["status"] not in {"applies", "port-required"}:
            raise ValueError(f"invalid status: {target['id']}")
        directory = ROOT / relative_path(target["patch_set"])
        names = series_names(directory, target.get("series", "series"))
        if set(target["patches"]) != set(names):
            raise ValueError(f"patch inventory changed: {target['id']}")
        for name, expected in target["patches"].items():
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
                raise ValueError(f"patch hash changed; refresh the target audit: {target['id']}/{name}")
        if not set(target.get("skip_patches", {})) <= set(names):
            raise ValueError(f"skip list references an unknown patch: {target['id']}")
        for item in target.get("skip_patches", {}).values():
            if item["status"] not in {"upstream", "superseded"} or not item["reason"]:
                raise ValueError(f"invalid skip reason: {target['id']}")
        files = target["files"]
        absent = target["absent_files"]
        if set(files) & set(absent) or len(absent) != len(set(absent)):
            raise ValueError(f"conflicting source preimages: {target['id']}")
        for name in [*files, *absent]:
            relative_path(name)
        if any(not re.fullmatch(r"[0-9a-f]{64}", h) for h in files.values()):
            raise ValueError(f"invalid source hash: {target['id']}")
        touched = set().union(*(patch_paths(directory / p) for p in names))
        if not touched <= set(files) | set(absent):
            raise ValueError(f"source hashes do not cover all patches: {target['id']}")
        base = target["base"]
        available_base = json.loads((directory / "base.json").read_text())
        available_base.pop("scope", None)
        if target["status"] == "applies" and available_base != base:
            raise ValueError(f"supported target still points to a different source base: {target['id']}")
        if "commit" in base:
            if not re.fullmatch(r"[0-9a-f]{40}", base["commit"]):
                raise ValueError(f"invalid commit: {target['id']}")
        elif not re.fullmatch(r"[0-9a-f]{64}", base["archive_sha256"]):
            raise ValueError(f"invalid archive identity: {target['id']}")
        if not target["tracking"]:
            raise ValueError(f"no upstream tracking: {target['id']}")
        for tracking in target["tracking"]:
            if tracking["kind"] == "git":
                if (not tracking["ref"].startswith("refs/")
                        or not re.fullmatch(r"[0-9a-f]{40}", tracking["commit"])):
                    raise ValueError(f"invalid tracking ref: {target['id']}")
                url = tracking["repository"]
            elif tracking["kind"] == "package":
                if not tracking["name"] or not tracking["version"]:
                    raise ValueError(f"invalid package tracking: {target['id']}")
                url = tracking["url"]
            else:
                raise ValueError(f"invalid tracking kind: {target['id']}")
            if urllib.parse.urlsplit(url).scheme != "https":
                raise ValueError(f"tracking URL must use HTTPS: {target['id']}")
    return manifest


def verify_source(target, source):
    if not source.is_dir() or source == Path("/"):
        raise ValueError("expected a source directory")
    if (source / ".git").exists() and "commit" in target["base"]:
        head = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True, timeout=10,
        ).strip()
        if head != target["base"]["commit"]:
            raise ValueError(f"wrong source commit: {head}")
    for name, expected in target["files"].items():
        path = source / name
        if path.resolve() != path or not path.is_file():
            raise ValueError(f"missing or symlinked source file: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"source hash mismatch: {name}")
    for name in target["absent_files"]:
        path = source / name
        if path.resolve() != path or path.exists():
            raise ValueError(f"expected new file to be absent: {name}")


def copy_source(target, source, destination):
    destination.mkdir()
    for name in target["files"]:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, path)


def apply_patch(directory, patch):
    result = subprocess.run(
        ["patch", "-d", str(directory), "-Np1", "--batch", "--forward", "--fuzz=0",
         "--no-backup-if-mismatch", "--reject-file=-", "-i", str(patch)],
        capture_output=True, text=True, timeout=30,
    )
    return {"status": "applies" if result.returncode == 0 else "fails",
            "log": result.stdout + result.stderr}


def check_target(target, source, series=None):
    verify_source(target, source)
    directory = ROOT / target["patch_set"]
    series = series or target.get("series", "series")
    names = series_names(directory, series)
    if not set(names) <= set(target["patches"]):
        raise ValueError("selected series contains unaudited patches")
    stack, isolated = [], []
    blocked_by = None
    with tempfile.TemporaryDirectory(prefix="experimental-compatibility-", dir="/tmp") as tmp:
        work = Path(tmp)
        copy_source(target, source, work / "stack")
        for index, name in enumerate(names):
            skip = target.get("skip_patches", {}).get(name)
            if skip:
                stack.append({"patch": name, **skip})
                isolated.append({"patch": name, **skip})
                continue
            # Isolated probes diagnose every patch, even after the full stack fails.
            # Dependent patches may fail here despite working in a complete series.
            fresh = work / str(index)
            copy_source(target, source, fresh)
            isolated.append({"patch": name, **apply_patch(fresh, directory / name)})
            if blocked_by:
                stack.append({"patch": name, "status": "blocked", "blocked_by": blocked_by})
                continue
            result = apply_patch(work / "stack", directory / name)
            stack.append({"patch": name, **result})
            if result["status"] == "fails":
                blocked_by = name
    return {"target": target["id"], "base": target["base"],
            "source": str(source), "source_verified": True,
            "scope": "Pinned touched-file preimages; application only. No build, boot or performance proof.",
            "patch_set": target["patch_set"], "series": series,
            "compatible": blocked_by is None,
            "stack": stack, "isolated_pristine_probes": isolated}


def package_versions(page, package):
    names = re.findall(r'href=["\']([^"\']+)["\']', page)
    versions = set()
    for name in names:
        name = urllib.parse.unquote(name.rsplit("/", 1)[-1])
        if not name.startswith(package + "-") or not name.endswith(".pkg.tar.zst"):
            continue
        tail = name[len(package) + 1:-len(".pkg.tar.zst")]
        parts = tail.rsplit("-", 2)
        if len(parts) == 3 and re.fullmatch(r"\d[^/\s]*", parts[0]):
            versions.add(parts[0] + "-" + parts[1])
    return sorted(versions)


def fetch_page(url):
    request = urllib.request.Request(url, headers={"User-Agent": "experimental-patches-compatibility/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode()


def remote_commit(repository, ref):
    parsed = urllib.parse.urlsplit(repository)
    if parsed.netloc == "github.com":
        project = parsed.path.strip("/").removesuffix(".git")
        api = "https://api.github.com/repos/" + project + "/git/"
        ref_path = urllib.parse.quote(ref.removeprefix("refs/"), safe="/")
        obj = json.loads(fetch_page(api + "ref/" + ref_path))["object"]
        # Source pins use commits, not the separate annotated-tag object IDs.
        for _ in range(4):
            if obj["type"] == "commit":
                return obj["sha"]
            if obj["type"] != "tag" or not obj["url"].startswith(api + "tags/"):
                raise ValueError("ref does not resolve to a commit")
            obj = json.loads(fetch_page(obj["url"]))["object"]
        raise ValueError("annotated tag chain is too deep")
    result = subprocess.run(["git", "ls-remote", repository, ref, ref + "^{}"],
                            check=True, capture_output=True, text=True, timeout=30)
    refs = dict(reversed(line.split()) for line in result.stdout.splitlines())
    return refs.get(ref + "^{}", refs.get(ref))


def check_updates(manifest):
    pages = {}
    urls = {t["url"] for target in manifest["targets"] for t in target["tracking"]
            if t["kind"] == "package"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        jobs = {url: executor.submit(fetch_page, url) for url in urls}
        for url, job in jobs.items():
            try:
                pages[url] = job.result()
            except Exception as exc:
                pages[url] = exc
    targets = []
    for target in manifest["targets"]:
        checks = []
        for tracking in target["tracking"]:
            result = dict(tracking)
            try:
                if tracking["kind"] == "git":
                    observed = remote_commit(tracking["repository"], tracking["ref"])
                    result.update(observed=observed, current=observed == tracking["commit"])
                elif tracking["kind"] == "package":
                    page = pages[tracking["url"]]
                    if isinstance(page, Exception):
                        raise page
                    observed = package_versions(page, tracking["name"])
                    # Multiple versions on one mirror require review, not a guessed maximum.
                    result.update(observed=observed, current=observed == [tracking["version"]])
                else:
                    raise ValueError("unknown tracking kind")
            except Exception as exc:
                result.update(current=False, error=str(exc))
            checks.append(result)
        targets.append({"id": target["id"], "patch_status": target["status"],
                        "tracking_current": all(c["current"] for c in checks), "checks": checks})
    return {"checked_at": datetime.datetime.now(datetime.UTC).isoformat(), "targets": targets,
            "all_current": all(t["tracking_current"] and t["patch_status"] == "applies"
                               for t in targets)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?")
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--series", help="override the target's recorded series")
    parser.add_argument("--list", action="store_true", help="list pinned test targets")
    parser.add_argument("--updates", action="store_true", help="read current public package/ref metadata")
    parser.add_argument("--output", type=Path, help="write the JSON report; use artifacts/check-compatibility/")
    args = parser.parse_args()
    try:
        manifest = load_manifest()
        if args.list:
            if args.target or args.source or args.updates:
                parser.error("--list takes no target, source or --updates")
            for target in manifest["targets"]:
                print(f"{target['id']:20} {target['version']:18} {target['status']:14} {target['patch_set']}")
            return 0
        if args.updates:
            if args.target or args.source:
                parser.error("--updates takes no target or source")
            report = check_updates(manifest)
            success = report["all_current"]
        else:
            if not args.target or not args.source:
                parser.error("supply TARGET SOURCE, --list or --updates")
            targets = {t["id"]: t for t in manifest["targets"]}
            if args.target not in targets:
                parser.error(f"unknown target: {args.target}")
            if args.output and args.output.resolve().is_relative_to(args.source.resolve()):
                raise ValueError("report output must be outside the supplied source tree")
            report = check_target(targets[args.target], args.source.resolve(), args.series)
            success = report["compatible"]
        text = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text)
        else:
            print(text, end="")
        return 0 if success else 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
