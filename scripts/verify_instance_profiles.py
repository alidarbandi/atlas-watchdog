"""Exercise real packaged cross-profile locks and crash recovery on a newer OS."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def verify(first, second, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(output / "LocalAppData")
    state = output / "shared copied state"
    first = str(Path(first).resolve())
    second = str(Path(second).resolve())
    results = []
    for index, (owner, secondary) in enumerate(((first, second), (second, first))):
        process = subprocess.Popen([owner, "--demo", "--state-dir", str(state)], env=env,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 15
            while not (state / "instance.lock").exists() or not (state / "history.sqlite3").exists():
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(.05)
            time.sleep(1)
            started = time.monotonic()
            result = subprocess.run([secondary, "--demo", "--smoke-test", "--state-dir", str(state)],
                                    env=env, capture_output=True, timeout=6, creationflags=subprocess.CREATE_NO_WINDOW)
            elapsed = time.monotonic() - started
            assert result.returncode == 0 and elapsed < 5 and process.poll() is None
            results.append(dict(direction=index + 1, secondary_exit=result.returncode, seconds=round(elapsed, 3)))
        finally:
            # Deliberately crash this disposable process only, to test stale lock recovery.
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        result = subprocess.run([secondary, "--demo", "--smoke-test", "--state-dir", str(state)],
                                env=env, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0, result.stderr
        results[-1]["crash_recovery_exit"] = result.returncode
    (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("first")
    parser.add_argument("second")
    parser.add_argument("output")
    args = parser.parse_args()
    verify(args.first, args.second, args.output)
