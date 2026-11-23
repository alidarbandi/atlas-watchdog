"""Prepare public assets from verified build outputs; no credentials or local state."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

VERSION = "0.1.7"
LEGACY = "ATLASWatchdog-Win10-1607-x64"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify_manifest(directory):
    manifest = directory / "SHA256SUMS.txt"
    for line in manifest.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = (directory / relative).resolve()
        if directory.resolve() not in path.parents or not path.is_file() or digest(path) != expected:
            raise ValueError(f"Invalid input manifest entry: {relative}")


def prepare(build_root, output, source_commit):
    build_root, output = Path(build_root).resolve(), Path(output).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("A full source commit SHA is required")
    if output.exists():
        raise ValueError("Use a fresh release staging directory; existing assets are preserved")
    profiles = {name: build_root / name for name in ("legacy", "modern")}
    for name, directory in profiles.items():
        verify_manifest(directory)
        metadata = json.loads((directory / "BUILD-DEPENDENCIES.json").read_text(encoding="utf-8"))
        if metadata["profile"] != name:
            raise ValueError("Artifact/profile mismatch")
    output.mkdir(parents=True)
    selected = {
        "legacy": [LEGACY + ".exe", LEGACY + "-debug.zip"],
        "modern": ["ATLASWatchdog.exe", "ATLASWatchdog-debug.zip", "ATLASWatchdog-source.zip"],
    }
    for profile, names in selected.items():
        for name in names:
            shutil.copy2(profiles[profile] / name, output / name)
    for name in (LEGACY + "-debug.zip", "ATLASWatchdog-debug.zip", "ATLASWatchdog-source.zip"):
        with ZipFile(output / name) as archive:
            if archive.testzip() is not None:
                raise ValueError(f"Corrupt input archive: {name}")
    # The full legacy download extracts a real legacy/ folder. Avoid duplicating
    # the diagnostic ZIP inside it; include its already-expanded complete folder.
    files = [path for path in sorted(profiles["legacy"].rglob("*")) if path.is_file()
             and path.name != "SHA256SUMS.txt" and path != profiles["legacy"] / (LEGACY + "-debug.zip")]
    folder_manifest = []
    with ZipFile(output / f"ATLASWatchdog-v{VERSION}-legacy.zip", "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            relative = path.relative_to(profiles["legacy"]).as_posix()
            archive.write(path, "legacy/" + relative)
            folder_manifest.append(f"{digest(path)}  {relative}")
        archive.writestr("legacy/SHA256SUMS.txt", "\n".join(folder_manifest) + "\n")
    record = dict(version=VERSION, source_commit=source_commit,
                  packaged_utc=datetime.now(timezone.utc).isoformat(),
                  source="GitHub Actions release build" if os.environ.get("GITHUB_ACTIONS") else "local release preparation",
                  owner_reported_legacy_startup="2026-11-23: previously delivered legacy build fixed the issue",
                  independent_exact_target_validation="PENDING; Windows CI is not Windows 1607 certification",
                  build_dependencies={name: json.loads((directory / "BUILD-DEPENDENCIES.json").read_text(encoding="utf-8"))
                                      for name, directory in profiles.items()})
    (output / "BUILD-RELEASE.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    (output / "SOURCE-COMMIT.txt").write_text(source_commit + "\n", encoding="ascii")
    entries = [f"{digest(path)}  {path.name}" for path in sorted(output.iterdir()) if path.is_file()]
    (output / "SHA256SUMS.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")
    print(f"Prepared {len(entries)} release assets plus SHA256SUMS.txt in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-root", default=f"dist/v{VERSION}")
    parser.add_argument("--output", default=f"dist/github-v{VERSION}")
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    prepare(args.build_root, args.output, args.source_commit)
