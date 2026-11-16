"""Qt-free profile selection, OS preflight and privacy-limited startup reports."""
from __future__ import annotations

import ctypes
import json
import os
import platform
import sys
import sysconfig
from datetime import datetime, timezone
from pathlib import Path

PROFILES = {
    "modern": (17763, "Windows 10 1809 / build 17763 or newer, x64"),
    "legacy": (14393, "Windows 10 1607 / build 14393 or newer, x64; target validation pending"),
}


def selected_profile():
    # A frozen artifact's runtime hook fixes its identity; the environment cannot
    # turn a Qt 6 artifact into a nominal legacy artifact.
    profile = (getattr(sys, "_atlas_watchdog_profile", "modern") if getattr(sys, "frozen", False)
               else os.environ.get("ATLAS_WATCHDOG_PROFILE", "modern"))
    if profile not in PROFILES:
        raise ValueError("ATLAS_WATCHDOG_PROFILE must be modern or legacy")
    return profile


def os_architecture():
    if sys.platform != "win32":
        return platform.machine().lower()

    class SystemInfo(ctypes.Structure):
        _fields_ = [("architecture", ctypes.c_ushort), ("reserved", ctypes.c_ushort),
                    ("page_size", ctypes.c_ulong), ("minimum", ctypes.c_void_p),
                    ("maximum", ctypes.c_void_p), ("mask", ctypes.c_size_t),
                    ("processors", ctypes.c_ulong), ("type", ctypes.c_ulong),
                    ("granularity", ctypes.c_ulong), ("level", ctypes.c_ushort),
                    ("revision", ctypes.c_ushort)]
    info = SystemInfo()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetNativeSystemInfo.argtypes = [ctypes.POINTER(SystemInfo)]
    kernel.GetNativeSystemInfo.restype = None
    kernel.GetNativeSystemInfo(ctypes.byref(info))
    return {9: "x64", 0: "x86", 12: "arm64"}.get(info.architecture, "unknown")


def baseline_errors(profile, system, major, minor, build, process_arch, os_arch):
    minimum, _ = PROFILES[profile]
    errors = []
    if system == "win32" and ((major, minor) < (10, 0) or build < minimum):
        errors.append("OS is below this profile's minimum build.")
    if system == "win32" and (process_arch != "x64" or os_arch != "x64"):
        errors.append("This artifact requires an x64 process and x64 Windows.")
    return errors


def preflight():
    profile = selected_profile()
    version = sys.getwindowsversion() if sys.platform == "win32" else None
    process_arch = {"win-amd64": "x64", "win32": "x86", "win-arm64": "arm64"}.get(
        sysconfig.get_platform(), platform.machine().lower())
    major, minor, build = (version.major, version.minor, version.build) if version else (0, 0, 0)
    revision = None
    if version:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as key:
                revision = winreg.QueryValueEx(key, "UBR")[0]
        except OSError:
            pass
    arch = os_architecture()
    return dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), profile=profile,
                system=sys.platform, major=major, minor=minor, build=build, revision=revision,
                process_architecture=process_arch, os_architecture=arch,
                python=platform.python_version(), expected_baseline=PROFILES[profile][1],
                target_os_validation="PENDING" if profile == "legacy" else "See verification report",
                errors=baseline_errors(profile, sys.platform, major, minor, build, process_arch, arch))


def write_startup_report(report, exc=None):
    # No command line, environment dump, machine/user name, exception message,
    # source text, credential reference or traceback local variables are saved.
    from .config import ConfigStore, safe_destination, state_directory
    directory = state_directory()
    destination = safe_destination(directory / "startup.json", ConfigStore(directory).load())
    record = dict(report)
    if exc is not None:
        frames = []
        trace = exc.__traceback__
        while trace:
            frames.append(dict(module=Path(trace.tb_frame.f_code.co_filename).name,
                               function=trace.tb_frame.f_code.co_name, line=trace.tb_lineno))
            trace = trace.tb_next
        record.update(status="failed", exception=type(exc).__name__, frames=frames,
                      winerror=getattr(exc, "winerror", None))
    else:
        record["status"] = "preflight_failed" if report["errors"] else "preflight_passed"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return destination


def native_error(message, *, console_only=False):
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    if sys.platform == "win32" and not console_only:
        ctypes.windll.user32.MessageBoxW(None, message, "ATLAS Watchdog startup failed", 0x10)
