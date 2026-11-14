"""Outbox/session checks use fake transports and deterministic injected clocks."""
from __future__ import annotations

import copy
import sqlite3
import threading

import pytest

from atlas_watchdog.controller import Controller
from atlas_watchdog.notifications import DeliveryResult


class Clock:
    def __init__(self):
        self.now = 100.0
        self.epoch = 10000.0

    def mono(self):
        return self.now

    def wall(self):
        return self.epoch

    def advance(self, amount):
        self.now += amount
        self.epoch += amount


class FakeSecrets:
    available = False

    def get(self, reference):
        return "fake-session-secret" if reference else ""


class Transport:
    def __init__(self, outcome=None, blocked=False):
        self.outcome = outcome or DeliveryResult("accepted", "Provider accepted test request")
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        if not blocked:
            self.release.set()

    def send(self, config, secret, recipient, subject, text):
        self.calls.append(dict(config=config, secret=secret, recipient=recipient, subject=subject, text=text))
        self.started.set()
        if not self.release.wait(5):
            raise RuntimeError("test failed to release fake transport")
        return self.outcome

    def get_me(self, secret):
        return {"username": "test_bot", "is_bot": True}

    def find_chats(self, secret):
        return [{"id": "100", "name": "First"}, {"id": "200", "name": "Second"}]


@pytest.fixture
def app(tmp_path):
    clock = Clock()
    gmail, telegram = Transport(), Transport()
    controller = Controller(tmp_path / "state", monotonic=clock.mono, wall=clock.wall,
                            transports={"gmail": gmail, "telegram": telegram}, secrets=FakeSecrets())
    config = copy.deepcopy(controller.config)
    config["channels"]["gmail"].update(enabled=True, sender="sender@example.com", recipients=["one@example.com"], credential_ref="session:gmail")
    config["channels"]["telegram"].update(enabled=True, chat_id="100", credential_ref="session:telegram")
    for name in ["engine", "execution"]:
        folder = tmp_path / "logs" / name
        folder.mkdir(parents=True)
        config["sources"][name]["folder"] = str(folder)
    controller.handle("configure", config)
    yield controller, clock, gmail, telegram
    gmail.release.set()
    telegram.release.set()
    for _, future in list(controller.inflight.values()):
        future.result(timeout=2)
    for _, _, future in controller.jobs:
        future.result(timeout=2)
    controller.close()


def enqueue(controller, message="A distinct synthetic fault", **changes):
    event = controller._synthetic("execution", message, severity="error")
    event.update(changes)
    controller._commit("execution", None, [event])
    return event


def rows(controller):
    return [dict(row) for row in controller.store.connection.execute("SELECT * FROM outbox ORDER BY id")]


def arm(controller):
    controller.handle("start")
    controller.handle("alerts", {"armed": True})


def settle(controller):
    for _, future in list(controller.inflight.values()):
        future.result(timeout=2)
    controller._collect_results()


def test_first_launch_and_armed_while_stopped_do_not_send(app):
    controller, _, gmail, telegram = app
    assert not controller.monitoring and not controller.alerts
    controller.handle("alerts", {"armed": True})
    enqueue(controller)
    controller._dispatch()
    assert not gmail.calls and not telegram.calls
    assert controller.alerts and not controller.monitoring
    assert {row["status"] for row in rows(controller)} == {"suppressed"}


def test_monitoring_without_alerts_stores_events_and_suppresses_channels(app):
    controller, _, gmail, telegram = app
    controller.handle("start")
    event = enqueue(controller)
    controller._dispatch()
    assert controller.store.event(event["id"]) is not None
    assert {row["status"] for row in rows(controller)} == {"suppressed"}
    assert not gmail.calls and not telegram.calls


@pytest.mark.parametrize("stop_command", ["alerts", "stop"])
def test_stop_then_rearm_cannot_send_previous_pending_items(app, stop_command):
    controller, _, gmail, telegram = app
    arm(controller)
    old_monitor, old_alert = controller.monitor_session, controller.alert_session
    old = enqueue(controller, "old fault")
    controller.handle(stop_command, {"armed": False})
    assert {row["status"] for row in rows(controller)} == {"suppressed"}
    if stop_command == "stop":
        assert controller.alerts  # Armed independently while monitoring is stopped.
        controller.handle("start")
        assert controller.monitor_session != old_monitor
    else:
        assert controller.monitoring
        controller.handle("alerts", {"armed": True})
        assert controller.alert_session != old_alert
    controller._dispatch()
    assert not gmail.calls and not telegram.calls
    current = enqueue(controller, "new distinct fault")
    controller._dispatch()
    settle(controller)
    assert len(gmail.calls) == len(telegram.calls) == 1
    assert current["id"] in gmail.calls[0]["subject"]
    assert old["id"] not in gmail.calls[0]["subject"]


def test_slow_gmail_does_not_block_telegram_or_controller_snapshot(app):
    controller, _, gmail, telegram = app
    gmail.release.clear()
    arm(controller)
    enqueue(controller)
    controller._dispatch()
    assert gmail.started.wait(1) and telegram.started.wait(1)
    controller.inflight["telegram"][1].result(timeout=1)
    controller._collect_results()
    assert controller.channel_status["telegram"]["state"] == "accepted"
    assert "gmail" in controller.inflight
    snapshot = controller.snapshot()
    assert snapshot["monitoring"] and snapshot["events"]
    assert controller.channel_status["gmail"]["state"] == "Sending"
    gmail.release.set()
    settle(controller)


@pytest.mark.parametrize("result", [DeliveryResult("retry", "temporary"), DeliveryResult("accepted", "accepted"), DeliveryResult("unknown", "uncertain")])
def test_stopping_inflight_records_acceptance_honestly_and_blocks_retry_after_rearm(app, result):
    controller, clock, gmail, _ = app
    gmail.release.clear()
    gmail.outcome = result
    arm(controller)
    enqueue(controller)
    controller._dispatch()
    assert gmail.started.wait(1)
    controller.handle("alerts", {"armed": False})
    controller.handle("alerts", {"armed": True})
    gmail.release.set()
    settle(controller)
    gmail_row = next(row for row in rows(controller) if row["channel"] == "gmail")
    expected = "suppressed" if result.status == "retry" else result.status
    assert gmail_row["status"] == expected
    clock.advance(1000)
    controller._dispatch()
    assert len(gmail.calls) == 1


def test_retries_respect_provider_delay_and_only_retry_failed_channel(app):
    controller, clock, gmail, telegram = app
    gmail.outcome = DeliveryResult("retry", "rate limited", retry_after=70)
    arm(controller)
    enqueue(controller)
    controller._dispatch()
    settle(controller)
    gmail_row = next(row for row in rows(controller) if row["channel"] == "gmail")
    assert gmail_row["status"] == "retry" and gmail_row["due"] >= clock.wall() + 70
    clock.advance(69)
    controller._dispatch()
    assert len(gmail.calls) == len(telegram.calls) == 1
    gmail.outcome = DeliveryResult("accepted", "accepted")
    clock.advance(2)
    controller._dispatch()
    settle(controller)
    assert len(gmail.calls) == 2 and len(telegram.calls) == 1


def test_explicit_channel_test_works_with_both_controls_off_and_is_test_labelled(app):
    controller, _, gmail, telegram = app
    controller.handle("test_channel", {"channel": "gmail"})
    controller.jobs[0][2].result(timeout=1)
    controller._collect_results()
    assert len(gmail.calls) == 1 and not telegram.calls
    assert "TEST" in gmail.calls[0]["subject"]
    assert not controller.monitoring and not controller.alerts
    assert "accepted" in controller.channel_status["gmail"]["test_result"]


def test_setup_chat_discovery_exposes_choices_without_selecting_one(app):
    controller, _, _, _ = app
    controller.handle("telegram_chats", {"channel": "telegram"})
    controller.jobs[0][2].result(timeout=1)
    controller._collect_results()
    assert len(controller.channel_status["telegram"]["chats"]) == 2
    assert controller.config["channels"]["telegram"]["chat_id"] == "100"


def test_historical_review_cannot_send_without_explicit_historical_option(app):
    controller, _, gmail, telegram = app
    controller.handle("start", {"mode": "review"})
    controller.handle("alerts", {"armed": True})
    enqueue(controller)
    controller._dispatch()
    assert {row["status"] for row in rows(controller)} == {"suppressed"}
    assert not gmail.calls and not telegram.calls
    controller.handle("start", {"mode": "review", "historical_alerts": True})
    enqueue(controller, "explicitly eligible historical event")
    controller._dispatch()
    settle(controller)
    assert len(gmail.calls) == len(telegram.calls) == 1


def test_explicit_resend_only_selected_unknown_event_does_not_retry_accepted(app):
    controller, clock, gmail, telegram = app
    arm(controller)
    first = enqueue(controller, "uncertain event")
    second = enqueue(controller, "accepted event")
    with controller.store.connection:
        controller.store.connection.execute("UPDATE outbox SET status='unknown' WHERE event_id=?", (first["id"],))
        controller.store.connection.execute("UPDATE outbox SET status='accepted' WHERE event_id=?", (second["id"],))
    controller.handle("replay_queue", {"ids": [first["id"]]})
    controller._dispatch()
    settle(controller)
    assert len(gmail.calls) == len(telegram.calls) == 1
    assert first["id"] in gmail.calls[0]["subject"]
    assert second["id"] not in gmail.calls[0]["subject"]


def test_old_persisted_queue_is_held_at_restart_and_never_automatically_replayed(app):
    controller, clock, gmail, telegram = app
    arm(controller)
    enqueue(controller, "prior process event")
    # Simulate prior-process state through a separate connection after orderly
    # stop; the subsequent Controller must audit it as crash leftovers.
    controller.handle("stop")
    path = controller.directory / "history.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE outbox SET status='pending' WHERE channel='gmail'")
        connection.execute("UPDATE outbox SET status='sending' WHERE channel='telegram'")
    resumed = Controller(controller.directory, monotonic=clock.mono, wall=clock.wall,
                         transports={"gmail": gmail, "telegram": telegram}, secrets=FakeSecrets())
    try:
        assert {row["status"] for row in rows(resumed)} == {"cancelled", "unknown"}
        assert not resumed.monitoring and not resumed.alerts
        arm(resumed)
        resumed._dispatch()
        assert not gmail.calls and not telegram.calls
    finally:
        resumed.close()


def test_token_bearing_result_text_is_redacted_in_automatic_and_setup_snapshots(app):
    controller, _, gmail, _ = app
    token = "123456789:unit-test-fake-token-only"
    gmail.outcome = DeliveryResult("failed", f"Error URL https://api.telegram.org/bot{token}/sendMessage")
    arm(controller)
    enqueue(controller)
    controller._dispatch()
    settle(controller)
    assert token not in str(controller.snapshot())
    controller.handle("test_channel", {"channel": "gmail"})
    controller.jobs[0][2].result(timeout=1)
    controller._collect_results()
    assert token not in str(controller.snapshot())


def test_stopped_request_queued_behind_setup_test_never_enters_transport(app):
    controller, _, gmail, _ = app
    gmail.release.clear()
    controller.handle("test_channel", {"channel": "gmail"})
    assert gmail.started.wait(1)
    arm(controller)
    enqueue(controller)
    controller._dispatch()
    assert "gmail" in controller.inflight
    controller.handle("alerts", {"armed": False})
    gmail.release.set()
    settle(controller)
    controller.jobs[0][2].result(timeout=1) if controller.jobs else None
    controller._collect_results()
    assert len(gmail.calls) == 1 and "TEST" in gmail.calls[0]["subject"]
    gmail_row = next(row for row in rows(controller) if row["channel"] == "gmail")
    assert gmail_row["status"] == "suppressed"


def test_changed_channel_configuration_starts_new_eligibility_session(app):
    controller, _, gmail, telegram = app
    arm(controller)
    enqueue(controller, "old recipients")
    old_session = controller.alert_session
    config = copy.deepcopy(controller.config)
    config["channels"]["gmail"]["recipients"] = ["new@example.com"]
    controller.handle("configure", config)
    assert controller.alert_session != old_session
    assert {row["status"] for row in rows(controller)} == {"suppressed"}
    controller._dispatch()
    assert not gmail.calls and not telegram.calls
    enqueue(controller, "new recipients")
    controller._dispatch()
    settle(controller)
    assert gmail.calls[0]["recipient"] == "new@example.com"


def test_per_recipient_failure_never_retries_already_accepted_recipient(app):
    controller, clock, gmail, _ = app
    config = copy.deepcopy(controller.config)
    config["channels"]["gmail"]["recipients"] = ["one@example.com", "rejected@example.com"]
    config["channels"]["telegram"]["enabled"] = False
    controller.handle("configure", config)
    original_send = gmail.send

    def recipient_result(config, secret, recipient, subject, text):
        original_send(config, secret, recipient, subject, text)
        return DeliveryResult("accepted" if recipient == "one@example.com" else "failed", "Mock recipient result")

    gmail.send = recipient_result
    arm(controller)
    enqueue(controller)
    controller._dispatch()
    settle(controller)
    clock.advance(4)
    controller._dispatch()
    settle(controller)
    statuses = {row["recipient"]: row["status"] for row in rows(controller)}
    assert statuses == {"one@example.com": "accepted", "rejected@example.com": "failed"}
    clock.advance(600)
    controller._dispatch()
    assert [call["recipient"] for call in gmail.calls] == ["one@example.com", "rejected@example.com"]
