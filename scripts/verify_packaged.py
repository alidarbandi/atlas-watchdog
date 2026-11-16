"""Build-host checks using only fresh demo state; no provider requests or secrets."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time


def verify(executable, output, repeats=2):
    executable, output = Path(executable).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    system_root = os.environ["SystemRoot"]
    env["PATH"] = os.pathsep.join([os.path.join(system_root, "System32"), system_root])
    env["LOCALAPPDATA"] = str(output / "LocalAppData")
    env["TEMP"] = env["TMP"] = str(output / "temporary extraction")
    Path(env["TEMP"]).mkdir()
    env.pop("PYTHONPATH", None)
    env.pop("QT_QPA_PLATFORM", None)
    # Try to override the fixed frozen profile; its report must still match the artifact.
    env["ATLAS_WATCHDOG_PROFILE"] = "modern" if "1607" in executable.name else "legacy"
    results = []
    for index in range(repeats):
        state = output / "demo state \u00e9"  # Repeat with the same state to check restart.
        started = time.monotonic()
        result = subprocess.run([str(executable), "--demo", "--smoke-test", "--state-dir", str(state),
                                 "--screenshot", str(output / f"window-{index}.png")],
                                env=env, capture_output=True, timeout=60,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        (output / f"stdout-{index}.txt").write_bytes(result.stdout)
        (output / f"stderr-{index}.txt").write_bytes(result.stderr)
        assert result.returncode == 0, f"Smoke exit {result.returncode}: {result.stderr!r}"
        with sqlite3.connect(state / "history.sqlite3") as connection:
            events = connection.execute("SELECT source,COUNT(*) FROM events GROUP BY source").fetchall()
            checkpoints = [(s, json.loads(cp)["offset"]) for s, cp in connection.execute("SELECT source,data FROM checkpoints")]
            sending = connection.execute("SELECT COUNT(*) FROM outbox WHERE status NOT IN ('suppressed','cancelled')").fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        assert any(source == "execution" and count for source, count in events)
        assert {s for s, offset in checkpoints if offset > 0} == {"engine", "execution"}
        assert integrity == "ok" and sending == 0
        report = json.loads((Path(env["LOCALAPPDATA"]) / "ATLASWatchdog" / "startup.json").read_text())
        expected = "legacy" if "1607" in executable.name else "modern"
        assert report["profile"] == expected
        results.append(dict(run=index + 1, seconds=round(time.monotonic() - started, 3), exit=result.returncode,
                            events=events, checkpoints=checkpoints, sqlite_integrity=integrity,
                            nonsuppressed_outbox=sending, embedded_profile=report["profile"]))
    (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("output")
    args = parser.parse_args()
    verify(args.executable, args.output)
