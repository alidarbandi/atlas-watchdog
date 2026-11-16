"""Bounded source GUI soak using disposable demo files and disabled alerts."""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import time

from atlas_watchdog.qt import QApplication, configure_dpi
from atlas_watchdog.gui import MainWindow


def resources():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                    *[(name, ctypes.c_size_t) for name in ("peak_working", "working", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]]
    process = ctypes.windll.kernel32.GetCurrentProcess
    process.restype = wintypes.HANDLE
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    assert psapi.GetProcessMemoryInfo(process(), ctypes.byref(counters), counters.cb)
    handles = wintypes.DWORD()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    assert kernel.GetProcessHandleCount(process(), ctypes.byref(handles))
    return dict(working_bytes=counters.working, handles=handles.value)


def soak(output, seconds):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ["LOCALAPPDATA"] = str(output / "LocalAppData")
    configure_dpi()
    app = QApplication.instance() or QApplication([])
    window = MainWindow(state_dir=str(output / "state"), enable_tray=False)
    window.show()
    started, last = time.monotonic(), time.monotonic()
    samples, actions = [], set()
    max_gap = 0
    initial_threads = None
    try:
        while time.monotonic() - started < seconds:
            now = time.monotonic()
            max_gap = max(max_gap, now - last)
            last = now
            app.processEvents()
            elapsed = now - started
            if window.loaded and "start" not in actions:
                window.send("demo", {"action": "start"})
                actions.add("start")
            for name, at in (("burst", 12), ("pause", 22), ("resume", 35), ("rotate", 48), ("truncate", 63)):
                if elapsed >= at and name not in actions:
                    window.send("demo", {"action": name})
                    actions.add(name)
            if window.current_snapshot.get("demo") and "timers" not in actions:
                import copy
                config = copy.deepcopy(window.current_snapshot["config"])
                for policy in config["sources"].values():
                    policy.update(expect_activity=True, inactivity_mode="duration", duration=5,
                                  grace=0, lifecycle_disarm=False, reminder_seconds=5)
                window.send("configure", config)
                actions.add("timers")
            if elapsed >= (len(samples) + 1) * 10:
                import threading
                counts = dict(resources(), threads=len(threading.enumerate()))
                initial_threads = initial_threads or counts["threads"]
                samples.append(dict(seconds=round(elapsed, 2), **counts))
                assert counts["threads"] <= initial_threads + 2
                assert not window.current_snapshot.get("alerts") and not window.current_snapshot.get("degraded")
                window.event_search.setText("")
                window.view_tabs.setCurrentIndex((len(samples) - 1) % window.view_tabs.count())
            time.sleep(.01)
        snapshot = window.current_snapshot
        assert snapshot.get("demo") and window.loaded
        assert all(snapshot["live"][name] for name in ("engine", "execution"))
        assert any(e.get("source") == "execution" for e in window.events)
        assert any("silence" in (e.get("type", "") + e.get("message", "")).lower() or "activity" in e.get("message", "").lower() for e in window.events), "No timer incident captured"
        report = dict(seconds=round(time.monotonic() - started, 3), max_event_pump_gap=round(max_gap, 3),
                      events=len(window.events), actions=sorted(actions), resources=samples)
        (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        assert max_gap < 2, f"GUI event-pump stall: {max_gap}"
    finally:
        window.shutdown()
        assert not window.thread.isRunning(), "Worker did not stop cleanly"
        window.close()
    report["clean_worker_shutdown"] = True
    (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args()
    assert 75 <= args.seconds <= 600
    soak(args.output, args.seconds)
