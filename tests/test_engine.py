import copy
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from atlas_watchdog.controller import Controller
from atlas_watchdog.storage import Store


class Clock:
    def __init__(self): self.now = 1000.0
    def monotonic(self): return self.now
    def wall(self): return 1_800_000_000 + self.now
    def advance(self, seconds=1): self.now += seconds


def line(message, level="Error"):
    return f"13/11/2026\t15:12:13.125\t{level}\tImaging\t\t{message}\r\n".encode()


@pytest.fixture
def engine(tmp_path):
    clock = Clock()
    c = Controller(tmp_path / "state", monotonic=clock.monotonic, wall=clock.wall)
    logs = tmp_path / "logs"
    logs.mkdir()
    config = copy.deepcopy(c.config)
    config["poll_seconds"] = 1
    for name in ["engine", "execution"]:
        config["sources"][name]["folder"] = str(logs)
        (logs / config["sources"][name]["filename"]).write_bytes(b"")
    c.handle("configure", config)
    yield c, clock, logs
    c.close()


def test_new_baseline_no_historical_alerts_and_source_independence(engine):
    c, clock, logs = engine
    execution = logs / "execution_log.log"
    execution.write_bytes(line("Historical failure"))
    before = hashlib.sha256(execution.read_bytes()).hexdigest()
    c.handle("start")
    c.tick()
    assert not c.snapshot()["events"]
    assert hashlib.sha256(execution.read_bytes()).hexdigest() == before
    with execution.open("ab") as out: out.write(line("Beam blanked"))
    clock.advance()
    c.tick()
    events = c.snapshot()["events"]
    assert len(events) == 1 and events[0]["source"] == "execution"
    assert events[0]["message"] == "Beam blanked"
    assert not c.live["engine"]
    assert c.sources["engine"]["checkpoint"]["offset"] == 0


def test_review_stores_history_and_marks_it(engine):
    c, clock, logs = engine
    (logs / "execution_log.log").write_bytes(line("Unable to recover. Stopping acquisition."))
    c.handle("start", {"mode": "review"})
    c.tick()
    events = c.snapshot()["events"]
    assert len(events) == 1
    assert events[0]["historical"]
    assert len(events[0]["rules"]) == 3
    assert not c.sources["execution"]["historical"]


def test_engine_activity_does_not_reset_execution_watch(engine):
    c, clock, logs = engine
    config = copy.deepcopy(c.config)
    config["sources"]["execution"].update(expect_activity=True, grace=0, cycles=3)
    c.handle("configure", config)
    c.handle("start")
    c.tick()
    for i in range(3):
        with (logs / "atlasengine.log").open("ab") as out: out.write(line(f"Engine activity {i}", "Log"))
        clock.advance()
        c.tick()
    events = c.snapshot()["events"]
    silence = [e for e in events if e["kind"] == "silence"]
    assert len(silence) == 1
    assert silence[0]["source"] == "execution"
    assert c.sources["engine"]["watch"].empty_cycles == 0
    assert c.sources["execution"]["watch"].empty_cycles == 4


def test_missing_engine_does_not_stop_execution(engine):
    c, clock, logs = engine
    (logs / "atlasengine.log").unlink()
    c.handle("start")
    c.tick()
    with (logs / "execution_log.log").open("ab") as out: out.write(line("Distinct fault"))
    clock.advance()
    c.tick()
    assert c.sources["engine"]["state"] == "Missing / Unreadable"
    assert c.sources["execution"]["state"] == "Monitoring"
    assert any(e["message"] == "Distinct fault" for e in c.snapshot()["events"])


def test_same_record_replay_deduplicated_and_cp_atomic(engine):
    c, clock, logs = engine
    c.handle("start")
    c.tick()
    previous = copy.deepcopy(c.sources["execution"]["checkpoint"])
    with (logs / "execution_log.log").open("ab") as out: out.write(line("Atomic fault"))
    clock.advance()
    c.tick()
    current = copy.deepcopy(c.sources["execution"]["checkpoint"])
    assert c.store.checkpoint("execution", str(logs / "execution_log.log")) == current
    c.sources["execution"]["checkpoint"] = previous
    clock.advance()
    c.tick()
    assert len([e for e in c.snapshot()["events"] if e["message"] == "Atomic fault"]) == 1


def test_sqlite_failure_keeps_checkpoint_and_bounded_emergency(engine, monkeypatch):
    c, clock, logs = engine
    c.handle("start")
    c.tick()
    previous = copy.deepcopy(c.sources["execution"]["checkpoint"])
    with (logs / "execution_log.log").open("ab") as out: out.write(line("Must survive state failure"))
    original = c.store.commit_batch
    def fail(*args, **kwargs): raise sqlite3.OperationalError("simulated disk full")
    monkeypatch.setattr(c.store, "commit_batch", fail)
    clock.advance()
    c.tick()
    assert c.sources["execution"]["checkpoint"] == previous
    assert c.degraded
    assert len(c.emergency) == 1 and c.emergency.maxlen == 100
    monkeypatch.setattr(c.store, "commit_batch", original)
    clock.advance()
    c.tick()
    assert c.sources["execution"]["checkpoint"]["offset"] > previous["offset"]
    assert any(e["message"] == "Must survive state failure" for e in c.store.events())


def test_database_rollback_never_advances_checkpoint(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    store.connection.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'simulated crash'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.commit_batch("engine", "example", {"offset": 42}, [{"id": "e", "message": "error", "severity": "error", "fingerprint": "f"}], {}, ("m", "a"), False, 100)
    assert store.checkpoint("engine", "example") is None
    assert store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    store.close()


def test_lifecycle_preserves_fault_acknowledgement_not_recovery(engine):
    c, clock, logs = engine
    config = copy.deepcopy(c.config)
    config["sources"]["execution"].update(expect_activity=True, grace=0, cycles=1)
    c.handle("configure", config)
    c.handle("start")
    c.tick()
    with (logs / "execution_log.log").open("ab") as out: out.write(line("Stopping acquisition") + line("Run Ended.", "Info"))
    clock.advance()
    c.tick()
    events = c.snapshot()["events"]
    fault = next(e for e in events if e["message"] == "Stopping acquisition")
    c.handle("acknowledge", {"id": fault["id"]})
    events = c.snapshot()["events"]
    assert any(e["id"] == fault["id"] and e["acknowledged"] for e in events)
    assert c.sources["execution"]["watch"].lifecycle_paused
    assert any(e["message"] == "Run Ended." and "success not inferred" in e["rule_names"][0] for e in events)


def test_future_rule_changes_no_rescan_and_path_change_stops(engine):
    c, clock, logs = engine
    c.handle("start")
    c.tick()
    with (logs / "atlasengine.log").open("ab") as out: out.write(line("WMAcqError", "Log"))
    clock.advance()
    c.tick()
    config = copy.deepcopy(c.config)
    next(r for r in config["rules"]["engine"] if r["pattern"] == "WMAcqError")["enabled"] = True
    c.handle("configure", config)
    clock.advance()
    c.tick()
    assert not c.snapshot()["events"]
    with (logs / "atlasengine.log").open("ab") as out: out.write(line("WMAcqError", "Log"))
    clock.advance()
    c.tick()
    assert len(c.snapshot()["events"]) == 1
    config["sources"]["engine"]["filename"] = "different.log"
    c.handle("configure", config)
    assert not c.monitoring


def test_export_no_raw_by_default_and_protect_sources(engine, tmp_path):
    c, clock, logs = engine
    (logs / "execution_log.log").write_bytes(line("Example event"))
    c.handle("start", {"mode": "review"})
    c.tick()
    output = tmp_path / "export.json"
    c.handle("export_history", {"path": str(output)})
    event = json.loads(output.read_text())[0]
    assert "message" in event and "path" not in event and "context" not in event and "raw_line" not in event
    with pytest.raises(ValueError): c.handle("export_history", {"path": str(logs / "execution_log.log")})
    with pytest.raises(ValueError): c.handle("export_config", {"path": str(logs / "config.json")})


def test_demo_safe_and_never_automatically_arms(engine):
    c, clock, logs = engine
    before = {p: p.read_bytes() for p in logs.iterdir()}
    c.handle("demo", {"action": "start"})
    for _ in range(12):
        c.tick()
        clock.advance()
    assert c.demo and not c.alerts
    assert any(e["source"] == "execution" for e in c.snapshot()["events"])
    with pytest.raises(ValueError): c.handle("alerts", {"armed": True})
    for action in ["burst", "rotate", "truncate", "pause", "resume"]: c.handle("demo", {"action": action})
    assert all(p.read_bytes() == content for p, content in before.items())


def test_restart_resume_marks_backlog_historical(engine):
    c, clock, logs = engine
    c.handle("start")
    c.tick()
    c.handle("stop")
    with (logs / "execution_log.log").open("ab") as out: out.write(line("Arrived while stopped"))
    c.handle("alerts", {"armed": True})
    c.handle("start", {"mode": "resume"})
    c.tick()
    assert next(e for e in c.snapshot()["events"] if e["message"] == "Arrived while stopped")["historical"]


def test_scheduling_gap_resets_grace(engine):
    c, clock, logs = engine
    c.handle("start")
    c.tick()
    clock.advance(500)
    c.tick()
    assert any(e["kind"] == "coverage" for e in c.snapshot()["events"])
    assert c.sources["execution"]["watch"].started == clock.now


def test_support_export_is_explicit_bounded_and_redacted(engine, tmp_path):
    c, clock, logs = engine
    c.handle("start")
    c.tick()
    with (logs / "execution_log.log").open("ab") as out: out.write(line("Scientific sample identifier"))
    clock.advance()
    c.tick()
    output = tmp_path / "support.json"
    c.handle("support_bundle", {"path": str(output)})
    text = output.read_text(encoding="utf-8")
    assert "Scientific sample identifier" not in text
    assert str(logs).replace("\\", "\\\\") not in text
    assert "[REDACTED]" in text
    with pytest.raises(ValueError): c.handle("support_bundle", {"path": str(logs / "bundle.json")})


def test_failed_review_commit_cannot_reclassify_history_as_live(engine, monkeypatch):
    c, clock, logs = engine
    (logs / "execution_log.log").write_bytes(line("Historical fault during storage outage"))
    c.handle("alerts", {"armed": True})
    c.handle("start", {"mode": "review"})
    original = c.store.commit_batch
    def fail(*args, **kwargs): raise sqlite3.OperationalError("simulated unavailable storage")
    monkeypatch.setattr(c.store, "commit_batch", fail)
    c._poll("execution")
    assert c.sources["execution"]["historical"]
    monkeypatch.setattr(c.store, "commit_batch", original)
    c._poll("execution")
    stored = c.store.events()
    assert next(e for e in stored if e["message"] == "Historical fault during storage outage")["historical"]


def test_initial_baseline_storage_failure_does_not_skip_future_records(engine, monkeypatch):
    c, clock, logs = engine
    c.handle("start")
    original = c.store.commit_batch
    def fail(*args, **kwargs): raise sqlite3.OperationalError("simulated unavailable storage")
    monkeypatch.setattr(c.store, "commit_batch", fail)
    c._poll("execution")
    assert c.sources["execution"]["checkpoint"] is None
    assert c.sources["execution"]["baseline_checkpoint"] is not None
    with (logs / "execution_log.log").open("ab") as out: out.write(line("Arrived after failed baseline commit"))
    monkeypatch.setattr(c.store, "commit_batch", original)
    c._poll("execution")
    assert any(e["message"] == "Arrived after failed baseline commit" for e in c.store.events())
