"""Fail a build with the wrong interpreter, unlocked packages or mixed Qt bindings."""
import os
import platform
import struct
import sys
from importlib.metadata import distributions
from pathlib import Path


def validate():
    profile = os.environ.get("ATLAS_WATCHDOG_PROFILE", "modern")
    assert profile in {"legacy", "modern"}, "Unknown profile"
    expected = (3, 10, 11) if profile == "legacy" else (3, 12, 13)
    assert sys.platform == "win32", "Build Windows binaries on Windows"
    assert sys.version_info[:3] == expected, f"Use CPython {expected}"
    assert struct.calcsize("P") == 8 and platform.machine().lower() in {"amd64", "x86_64"}, "Use x64 Python"
    root = Path(__file__).resolve().parents[1]
    lock = root / ("requirements-legacy-lock.txt" if profile == "legacy" else "requirements-lock.txt")
    installed = {d.metadata["Name"].lower().replace("_", "-"): d.version for d in distributions()}
    for line in lock.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, version = line.split("==")
        assert installed.get(name) == version, f"Lock mismatch: {name}=={version}"
    forbidden = ("pyside6", "shiboken6", "pyqt5", "pyqt6") if profile == "legacy" else ("pyside2", "shiboken2", "pyqt5", "pyqt6")
    assert not any(name in installed for name in forbidden), "Use isolated environments; multiple Qt bindings found"
    print(f"Validated {profile}: CPython {platform.python_version()} x64 and {lock.name}")


if __name__ == "__main__":
    validate()
