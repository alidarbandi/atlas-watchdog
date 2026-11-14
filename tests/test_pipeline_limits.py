import copy
import json

from atlas_watchdog.controller import Controller


def configured(tmp_path):
    c = Controller(tmp_path / "state", monotonic=lambda:1000, wall=lambda:1800000000)
    logs = tmp_path / "source"
    logs.mkdir()
    config = copy.deepcopy(c.config)
    config["mode"] = "execution"
    config["sources"]["execution"]["folder"] = str(logs)
    config["channels"]["gmail"].update(enabled=True, sender="sender@example.org", recipients=["first@example.org", "second@example.org"])
    file = logs / "execution_log.log"
    file.write_bytes(b"")
    c.handle("configure", config)
    c.handle("alerts", {"armed": True})
    c.handle("start")
    c._poll("execution")
    return c, file


def append_faults(file, messages):
    with file.open("ab") as f:
        for message in messages:
            f.write(f"13/11/2026\t15:00:00.000\tError\tImaging\t\t{message}\r\n".encode())


def test_burst_preserves_occurrences_sends_first_and_one_digest(tmp_path):
    c, file = configured(tmp_path)
    try:
        append_faults(file, ["Repeated target 0.8428"] * 40)
        c._poll("execution")
        events = c.store.events()
        assert len(events) == 40
        assert all(e["count"] == 40 for e in events)
        rows = c.store.connection.execute("SELECT * FROM outbox").fetchall()
        assert len(rows) == 80
        pending = [r for r in rows if r["status"] == "pending"]
        assert len(pending) == 4  # first + digest, separately for two recipients
        assert sum(r["due"] == 1800000000 for r in pending) == 2
        assert sum(r["due"] == 1800000030 for r in pending) == 2
        assert all("Grouped" in r["detail"] for r in rows if r["status"] == "suppressed")
    finally: c.close()


def test_numerically_different_fault_not_grouped(tmp_path):
    c, file = configured(tmp_path)
    try:
        append_faults(file, ["Failed target 0.8428 actual 1.3925", "Failed target 0.8429 actual 1.3925"])
        c._poll("execution")
        events = c.store.events()
        assert len({e["fingerprint"] for e in events}) == 2
        assert all(e["count"] == 1 for e in events)
        assert c.store.connection.execute("SELECT COUNT(*) FROM outbox WHERE due=1800000000 AND status='pending'").fetchone()[0] == 4
    finally: c.close()


def test_outbox_capacity_keeps_event_and_reports_overflow(tmp_path):
    c, file = configured(tmp_path)
    try:
        c.config["max_outbox"] = 10
        append_faults(file, [f"Distinct critical target {i}" for i in range(10)])
        c._poll("execution")
        assert len(c.store.events()) == 10
        assert c.store.connection.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0] == 10
        failed = c.store.connection.execute("SELECT * FROM outbox WHERE status='failed'").fetchall()
        assert len(failed) == 10
        assert all("capacity" in r["detail"] for r in failed)
    finally: c.close()


def test_history_cap_holds_checkpoint_bounds_memory_and_recovery(tmp_path):
    c, file = configured(tmp_path)
    try:
        c.config["max_events"] = 100
        append_faults(file, [f"Fault {i}" for i in range(100)])
        c._poll("execution")
        checkpoint = copy.deepcopy(c.sources["execution"]["checkpoint"])
        append_faults(file, [f"Additional fault {i}" for i in range(150)])
        c._poll("execution")
        assert len(c.store.events()) == 100
        assert c.sources["execution"]["checkpoint"] == checkpoint
        assert c.capacity_blocked and c.degraded
        assert len(c.emergency) == 100
        c.handle("stop")
        c.handle("clear_history")
        assert not c.capacity_blocked
    finally: c.close()


def test_retention_preserves_unacknowledged_and_unresolved_faults(tmp_path):
    c, file = configured(tmp_path)
    try:
        append_faults(file, ["Persistent unacknowledged fault", "Acknowledged but unresolved fault"])
        c._poll("execution")
        events = c.store.events()
        c.store.acknowledge(events[0]["id"])
        count = c.store.cleanup(1900000000, days=1, max_events=1)
        assert count == 2
        with c.store.connection:
            c.store.connection.execute("UPDATE outbox SET status='accepted'")
        count = c.store.cleanup(1900000000, days=1, max_events=1)
        assert count == 1
        assert not c.store.events()[0]["acknowledged"]
    finally: c.close()


def test_deliberate_discard_is_final_not_reoffered_or_replayed(tmp_path):
    c, file = configured(tmp_path)
    try:
        append_faults(file, ["Fault to discard"])
        c._poll("execution")
        c.handle("stop")
        # Model the restart-held state.
        with c.store.connection:
            c.store.connection.execute("UPDATE outbox SET status='cancelled',detail='Previous session'")
        assert c.store.pending_count() == 2
        event = c.store.events()[0]
        c.handle("discard_queue", {"ids": [event["id"]]})
        assert c.store.pending_count() == 0
        c.handle("start")
        c.handle("replay_queue")
        rows = c.store.connection.execute("SELECT status,detail FROM outbox").fetchall()
        assert all(r["status"] == "cancelled" and r["detail"] == "Deliberately discarded" for r in rows)
        c.store.acknowledge(event["id"])
        assert c.store.cleanup(1900000000, 1, 100) == 0
    finally: c.close()


def test_corrupt_checkpoint_json_is_reset_with_visible_gap(tmp_path):
    c, file = configured(tmp_path)
    try:
        c.handle("stop")
        with c.store.connection:
            c.store.connection.execute("UPDATE checkpoints SET data='broken JSON' WHERE source='execution'")
        append_faults(file, ["Fault after corrupted checkpoint"])
        c.handle("start", {"mode":"resume"})
        c._poll("execution")
        assert any("checkpoint" in d.lower() and "gap" in d.lower() for d in c.diagnostics)
        assert any(e["message"] == "Fault after corrupted checkpoint" and e["historical"] for e in c.store.events())
    finally: c.close()
