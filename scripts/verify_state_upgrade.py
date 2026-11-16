"""Seed old source state, copy it, then check both profiles; no real credentials."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


class FakeSecrets:
    available = False
    def get(self, reference):
        return ""


def phase(directory, seed):
    from atlas_watchdog.controller import Controller
    clock = [100.0]
    controller = Controller(str(directory), monotonic=lambda: clock[0], secrets=FakeSecrets())
    try:
        if seed:
            sources = directory.parent / "sources"
            sources.mkdir()
            config = controller.config
            config.update(instrument="Disposable compatibility fixture", poll_seconds=1)
            config["channels"]["gmail"]["credential_ref"] = "wincred:unit-test-upgrade-placeholder"
            for source in ("engine", "execution"):
                path = sources / (source + ".log")
                path.write_bytes(b"13/11/2026\t12:00:01.123\tError\tTest\t\tDisposable compatibility fault\r\n")
                config["sources"][source].update(folder=str(sources), filename=path.name)
            controller.handle("configure", config)
            controller.handle("start", {"mode": "review"})
            for _ in range(4):
                clock[0] += 2
                controller.tick()
        else:
            assert not controller.monitoring and not controller.alerts
            assert controller.config["instrument"] == "Disposable compatibility fixture"
            assert controller.config["channels"]["gmail"]["credential_ref"] == "wincred:unit-test-upgrade-placeholder"
        checkpoints = list(controller.store.connection.execute("SELECT source,path,data FROM checkpoints ORDER BY source"))
        events = list(controller.store.connection.execute("SELECT id,source,message FROM events ORDER BY id"))
        assert len(checkpoints) == 2 and len(events) >= 2
        result = dict(checkpoints=[list(row) for row in checkpoints], events=[list(row) for row in events])
        print(json.dumps(result))
    finally:
        controller.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--baseline-source")
    parser.add_argument("--legacy-python")
    parser.add_argument("--phase", choices=["seed", "check"])
    args = parser.parse_args()
    if args.phase:
        phase(Path(args.output), args.phase == "seed")
    else:
        output = Path(args.output).resolve()
        output.mkdir(parents=True, exist_ok=False)
        env = os.environ.copy()
        env["LOCALAPPDATA"] = str(output / "LocalAppData")
        env["PYTHONPATH"] = str(Path(args.baseline_source).resolve() / "src")
        script = str(Path(__file__).resolve())
        baseline = subprocess.check_output([sys.executable, script, str(output / "old-state"), "--phase", "seed"], env=env, text=True)
        shutil.copytree(output / "old-state", output / "copied-state")
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        for profile, python in (("legacy", args.legacy_python), ("modern", sys.executable)):
            env["ATLAS_WATCHDOG_PROFILE"] = profile
            result = subprocess.check_output([python, script, str(output / "copied-state"), "--phase", "check"], env=env, text=True)
            assert json.loads(result) == json.loads(baseline), f"{profile} changed history/cursors"
        (output / "result.txt").write_text("Original 0.1.6 state copy retained config, credential reference, exact events and checkpoints across legacy and modern; launch controls off.\n", encoding="utf-8")
        print((output / "result.txt").read_text())
