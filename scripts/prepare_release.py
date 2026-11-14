"""Gather local release docs/source and hashes; never includes credentials or user logs."""
from __future__ import annotations

import hashlib
import argparse
import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main(release_dir=None):
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
    source_archive = release / "ATLASWatchdog-source.zip"
    allowed = ["src", "tests", "docs", "scripts", "packaging", ".github", "README.md",
               "LICENSE", "THIRD_PARTY_NOTICES.md", "pyproject.toml", "requirements-lock.txt", ".gitignore"]
    with ZipFile(source_archive, "w", compression=ZIP_DEFLATED) as archive:
        for item in allowed:
            candidate = root / item
            files = [candidate] if candidate.is_file() else candidate.rglob("*")
            for path in files:
                if not path.is_file() or "__pycache__" in path.parts or any(part.endswith(".egg-info") for part in path.parts) or path.suffix == ".pyc" or path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                    continue
                archive.write(path, str(Path("ATLASWatchdog-source") / path.relative_to(root)))
    debug_folder = release / "ATLASWatchdog-debug"
    debug_archive = release / "ATLASWatchdog-debug.zip"
    if debug_folder.is_dir():
        with ZipFile(debug_archive, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(debug_folder.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(release))
    targets = [release / "ATLASWatchdog.exe", debug_archive, source_archive]
    manifest = []
    for path in targets:
        if path.exists():
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            manifest.append(f"{digest}  {path.relative_to(release).as_posix()}")
    (release / "SHA256SUMS.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    print(f"Release docs, source archive and hashes prepared in {release}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="Versioned release folder within dist")
    main(parser.parse_args().output)
