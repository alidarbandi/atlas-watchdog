"""Gather local release docs/source and hashes; never includes credentials or user logs."""
from __future__ import annotations

import hashlib
import argparse
import shutil
import json
import platform
import sqlite3
import ssl
from importlib.metadata import distributions
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main(release_dir=None, profile="modern"):
    root = Path(__file__).resolve().parents[1]
    release = (Path(release_dir) if release_dir else root / "dist").resolve()
    if release != root / "dist" and root / "dist" not in release.parents:
        raise ValueError("Release output must stay within this project's dist directory.")
    release.mkdir(parents=True, exist_ok=True)
    for name in ["README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"]:
        shutil.copy2(root / name, release / name)
    for document in (root / "docs").rglob("*"):
        if document.is_file() and document.suffix.lower() in {".md", ".txt", ".json"}:
            target = release / document.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(document, target)
    shutil.copy2(root / "scripts" / "check-windows.ps1", release / "check-windows.ps1")
    shutil.copy2(root / "scripts" / "test-candidate.ps1", release / "test-candidate.ps1")
    for name in ("requirements-lock.txt", "requirements-legacy-lock.txt"):
        shutil.copy2(root / name, release / name)
    metadata = []
    for dist in distributions():
        # Editable-project metadata contains private absolute source locations.
        if dist.metadata["Name"].lower() == "atlas-watchdog":
            continue
        metadata.append(dict(name=dist.metadata["Name"], version=dist.version,
                             requires_python=dist.metadata.get("Requires-Python"),
                             requires_dist=dist.metadata.get_all("Requires-Dist") or [],
                             wheel=dist.read_text("WHEEL")))
    record = dict(profile=profile, python=platform.python_version(),
                  sqlite=sqlite3.sqlite_version, openssl=ssl.OPENSSL_VERSION,
                  target_os_validation="PENDING", dependencies=metadata)
    (release / "BUILD-DEPENDENCIES.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    if profile == "legacy":
        (release / "UNVERIFIED-ON-TARGET-OS.txt").write_text(
            "UNVERIFIED ON THE TARGET OS\nWindows 10 Enterprise 2016 LTSB 1607 build 14393.3884 x64 has NOT been tested.\n"
            "Run check-windows.ps1 -Profile legacy, then follow docs/legacy-acceptance.md on a disposable test PC.\n", encoding="utf-8")
        (release / "START-HERE.txt").write_text(
            "ATLAS Watchdog 0.1.7 - Windows 10 1607 x64 LEGACY CANDIDATE\n\n"
            "UNVERIFIED ON THE TARGET OS (14393.3884).\n"
            "1. Confirm x64 using check-windows.ps1 -Profile legacy.\n"
            "2. Extract the complete debug ZIP and begin with the demo using new state; see docs/legacy-acceptance.md.\n"
            "3. The portable app is ATLASWatchdog-Win10-1607-x64.exe. Python/Qt installation is not required.\n"
            "4. Monitoring and automatic alerts start OFF. Configure and test deliberately before use.\n"
            "Build-host tests passed; exact-target, clean-machine, real acquisition and real delivery checks remain pending.\n"
            "This compatibility runtime uses old Python/Qt/OpenSSL versions; see docs/legacy-build.md.\n", encoding="utf-8")
    source_archive = release / "ATLASWatchdog-source.zip"
    allowed = ["src", "tests", "docs", "scripts", "packaging", ".github", "README.md",
               "LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml", "requirements-lock.txt", "requirements-legacy-lock.txt", ".gitignore"]
    with ZipFile(source_archive, "w", compression=ZIP_DEFLATED) as archive:
        for item in allowed:
            candidate = root / item
            files = [candidate] if candidate.is_file() else candidate.rglob("*")
            for path in files:
                if not path.is_file() or "__pycache__" in path.parts or any(part.endswith(".egg-info") for part in path.parts) or path.suffix == ".pyc" or path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                    continue
                archive.write(path, str(Path("ATLASWatchdog-source") / path.relative_to(root)))
    artifact = "ATLASWatchdog-Win10-1607-x64" if profile == "legacy" else "ATLASWatchdog"
    debug_folder = release / (artifact + "-debug")
    debug_archive = release / (artifact + "-debug.zip")
    if debug_folder.is_dir():
        with ZipFile(debug_archive, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(debug_folder.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(release))
    targets = [p for p in sorted(release.rglob("*")) if p.is_file() and debug_folder not in p.parents and p.name != "SHA256SUMS.txt"]
    manifest = []
    for path in targets:
        if path.exists():
            with path.open("rb") as source:
                hasher = hashlib.sha256()
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    hasher.update(block)
                digest = hasher.hexdigest()
            manifest.append(f"{digest}  {path.relative_to(release).as_posix()}")
    (release / "SHA256SUMS.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(f"Release docs, source archive and hashes prepared in {release}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Versioned release folder within dist")
    parser.add_argument("--profile", choices=["modern", "legacy"], default="modern")
    args = parser.parse_args()
    main(args.output, args.profile)
