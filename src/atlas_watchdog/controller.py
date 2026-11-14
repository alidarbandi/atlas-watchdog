"""Worker-owned application services and independent monitor/alert sessions.

SQLite is used only on the constructing thread. Channel pools never touch it.
Every checkpoint commit includes matched events and recipient outbox rows.
"""
from __future__ import annotations

import copy
import csv
import errno
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import random
import shutil
import sqlite3
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .activity import ActivityWatch
from .config import ConfigStore, portable_config, safe_destination, source_path, state_directory, validate
from .demo import DemoWriter
from .notifications import DeliveryResult, GmailTransport, TelegramTransport, redact
from .parser import parse_line
from .rules import evaluate
from .secrets import SecretStore
from .storage import Store
from .tailer import read_batch


def stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def source_read_error(exc):
    """Explain the failed read without probing metadata or substituting paths."""
    winerror = getattr(exc, "winerror", None)
    code = winerror if winerror is not None else getattr(exc, "errno", None)
    if winerror == 3:
        return "Source folder not found (Windows code 3). In Sources, choose the actual log file or its containing folder. The prefilled engine folder is an unverified suggestion."
    if winerror == 2 or (winerror is None and code == errno.ENOENT):
        return "Log file not found (code 2). Check the selected folder and filename, or wait for ATLAS to create the log. The watchdog will not create it."
    if winerror == 5 or (winerror is None and code in {errno.EACCES, errno.EPERM}):
        return "Source access denied. Check normal read permissions for the selected log; the watchdog will keep retrying without changing permissions."
    if winerror in {32, 33}:
        return f"Source read blocked by file sharing or a lock (Windows code {winerror}). ATLAS may deny readers; the watchdog will retry without bypassing protection."
    if winerror in {53, 67}:
        return f"Source network path unavailable (Windows code {winerror}). Check the explicitly selected share and network connection."
    if code is not None:
        return f"Source read failed (code {code}). Check the selected path and source availability; the watchdog will retry."
    return "Source encoding/read configuration invalid. Check the selected source encoding."


class Controller:
    def __init__(self, state_dir=None, *, monotonic=time.monotonic, wall=time.time, transports=None, secrets=None):
        self.clock, self.wall = monotonic, wall
        directory = Path(state_dir) if state_dir else state_directory()
        self.config_store = ConfigStore(directory)
        self.config = self.config_store.load()
        self.directory = safe_destination(directory, self.config, state=True)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.directory / "history.sqlite3")
        self.secret_store = secrets or SecretStore()
        self.transports = transports or {"gmail": GmailTransport(), "telegram": TelegramTransport()}
        self.pools = {c: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"atlas-{c}") for c in self.transports}
        self.inflight = {}
        self.jobs = []
        self.next_send = {c: 0.0 for c in self.transports}
        self.gate = threading.Event()
        self.monitoring = self.alerts = False
        self.monitor_session = self.alert_session = ""
        self.sources = {}
        self.live = {c: deque(maxlen=1000) for c in ["engine", "execution"]}
        self.context = {c: deque(maxlen=12) for c in self.live}
        self.diagnostics = deque(maxlen=100)
        self.emergency = deque(maxlen=100)
        self.degraded = False
        self.capacity_blocked = False
        self.groups = {}
        self.channel_status = {c: dict(last_success="", last_error="", state="Off") for c in self.transports}
        self.last_tick = self.clock()
        self.last_cleanup = self.last_tick - 60
        self.demo = None
        self.production_config = None
        self.demo_next = 0
        self.history_offset = 0
        self.history_limit = 300
        self.log = logging.getLogger("atlas-watchdog." + uuid.uuid4().hex)
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        handler = RotatingFileHandler(self.directory / "diagnostics.log", maxBytes=524288, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.log.addHandler(handler)
        for name in self.live:
            self._source_init(name, "new")
        if self.config_store.warning:
            self._diagnostic(self.config_store.warning)
        if self.store.pending_count():
            self._diagnostic("Previous undelivered items are held. Deliberately resend or discard from History; automatic sending starts off.")

    def _diagnostic(self, message, level=logging.WARNING):
        message = self._redact(message)
        self.diagnostics.append(f"{stamp()} {message}")
        self.log.log(level, message)

    def _redact(self, message):
        values = [self.secret_store.get(c["credential_ref"]) for c in self.config["channels"].values() if c.get("credential_ref")]
        return redact(message, values)

    def _enabled(self):
        return ["engine", "execution"] if self.config["mode"] == "both" else [self.config["mode"]]

    def _source_init(self, name, mode):
        now = self.clock()
        path = str(source_path(self.config, name).resolve())
        # A fresh session cannot inherit context from the end of an old review.
        self.context[name].clear()
        self.sources[name] = dict(state="Stopped", path=path, last_read="", last_bytes="", last_record="", log_timestamp="",
                                  next_check=now, backlog=0, quiet_seconds=0, empty_cycles=0, watch_status="Not armed", recent_errors=0,
                                  checkpoint=self.store.checkpoint(name, path) if mode == "resume" else None,
                                  baseline_checkpoint=None,
                                  mode=mode, historical=mode in {"review", "resume"}, historical_alerts=False,
                                  watch=ActivityWatch(copy.deepcopy(self.config["sources"][name]), now),
                                  read_error="", read_error_count=0, incomplete_since=now, incomplete_warned=False, encoding="")

    def _new_gate(self):
        self.gate.clear()
        self.gate = threading.Event()
        if self.monitoring and self.alerts:
            self.gate.set()

    def _recipients(self):
        g, t = self.config["channels"]["gmail"], self.config["channels"]["telegram"]
        return dict(gmail=list(g["recipients"]) if g["enabled"] else [], telegram=[t["chat_id"]] if t["enabled"] and t["chat_id"] else [])

    def _synthetic(self, name, message, severity="warning", kind="health", notify=True):
        record = parse_line(message, name)
        # A watchdog health event is not a line parsed from the ATLAS log.
        record.update(level="Not applicable", component="ATLAS Watchdog", raw_line="", raw_b64="", diagnostic="", origin="watchdog")
        record.update(id=uuid.uuid4().hex, severity=severity, rules=[], rule_names=[kind], channels=["gmail", "telegram"],
                      path=self.sources[name]["path"], context=list(self.context[name]), historical=False, notify=notify,
                      fingerprint=hashlib.sha256((name + kind + message).encode()).hexdigest(), count=1, kind=kind)
        return record

    def _commit(self, name, checkpoint, events):
        s = self.sources[name]
        for event in events:
            event.setdefault("monitor_session", self.monitor_session)
        eligible = self.monitoring and self.alerts
        if s["historical"] and not s["historical_alerts"]:
            eligible = False
        try:
            if self.capacity_blocked:
                self.emergency.extend(events)
                self.degraded = True
                return None
            count = self.store.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            if count + len(events) > self.config["max_events"]:
                self.capacity_blocked = self.degraded = True
                self.emergency.extend(events)
                self._diagnostic("History capacity reached — checkpoint held; bounded emergency history active. Export/acknowledge/delete stored history.")
                return None
            inserted = self.store.commit_batch(name, s["path"], checkpoint, events, self._recipients(),
                                               (self.monitor_session, self.alert_session), eligible, self.wall(), self.config["max_outbox"])
            if checkpoint is not None:
                s["checkpoint"] = checkpoint
                s["baseline_checkpoint"] = None
            self.degraded = False
            return inserted
        except (sqlite3.Error, OSError):
            self.degraded = True
            self.emergency.extend(events)
            self._diagnostic("State storage unavailable — bounded emergency history only; checkpoint held, reliability degraded. Check disk space/permissions.")
            return None

    def _record_event(self, name, raw, checkpoint, historical):
        record = parse_line(raw.text, name, raw.raw_b64, raw.diagnostic, self.config["sources"][name]["timezone"])
        match = evaluate(self.config["rules"][name], record)
        lifecycle = self.sources[name]["watch"].record(record, self.clock())
        identifier = hashlib.sha256(f"{name}:{checkpoint['generation']}:{raw.offset}".encode()).hexdigest()[:32]
        self.live[name].append(record["raw_line"] + ("  [" + record["diagnostic"] + "]" if record["diagnostic"] else ""))
        diagnostic = record.get("diagnostic", "")
        # CP1252 is an expected sample fallback, still visible in live/details without generating thousands of events.
        structural_problem = diagnostic and not diagnostic.startswith("Strict UTF-8 failed")
        event = None
        if match["matched"] or match["ignored"] or lifecycle or structural_problem:
            record.update(id=identifier, rules=match["rules"], rule_names=match["rule_names"], severity=match["severity"],
                          channels=match["channels"] if match["matched"] else [], path=self.sources[name]["path"],
                          context=list(self.context[name]), count=1, acknowledged=False, historical=historical,
                          ignored=match["ignored"], notify=match["matched"], offset=raw.offset,
                          kind="match" if match["matched"] else "ignored" if match["ignored"] else "lifecycle" if lifecycle else "parse-health")
            if not match["matched"]:
                record["rule_names"] = ["Ignored by " + ",".join(match["ignored"])] if match["ignored"] else ["Run ended / paused; success not inferred"] if lifecycle else ["Parse/decode health"]
                record["severity"] = "warning" if structural_problem else "info"
            record["fingerprint"] = hashlib.sha256((name + record["level"] + record["message"] + json.dumps(match["rules"])).encode()).hexdigest()
            self._group(record)
            event = record
        self.context[name].append(record["raw_line"])
        self.sources[name]["last_record"] = record["receipt_local"]
        self.sources[name]["log_timestamp"] = record["timestamp_original"] or self.sources[name]["log_timestamp"]
        return event

    def _group(self, event):
        now = self.wall()
        key = (event["source"], event["fingerprint"])
        group = self.groups.get(key)
        window = self.config["grouping_seconds"]
        if not group or now > group["end"] or not window:
            group = dict(start=now, end=now + window, first=event["id"], followup="")
            self.groups[key] = group
        elif not group["followup"]:
            group["followup"] = event["id"]
        event.update(group_start=group["start"], group_end=group["end"], group_first=group["first"], group_followup=group["followup"])
        if len(self.groups) > 2000:
            self.groups = {k: v for k, v in self.groups.items() if v["end"] >= now}
            if len(self.groups) > 2000:
                self.groups.pop(next(iter(self.groups)))

    def _poll(self, name):
        s = self.sources[name]
        now = self.clock()
        policy = self.config["sources"][name]
        interval = policy["interval"] or self.config["poll_seconds"]
        s["next_check"] = now + interval
        if not policy["folder"]:
            self._read_failure(name, "Waiting — select this source's folder")
            return
        try:
            read_checkpoint = s["checkpoint"] if s["checkpoint"] is not None else s["baseline_checkpoint"]
            # An ongoing observation session must never replay old faults just
            # because an editor/producer rewrote or replaced the file.
            reset_policy = "new" if s["mode"] == "new" or not s["historical"] else "review"
            batch = read_batch(s["path"], read_checkpoint, s["mode"], policy["encoding"], reset_policy=reset_policy)
        except (OSError, ValueError) as exc:
            # File errors are not log contents. Avoid unexpected exception text and paths in diagnostics.
            self._read_failure(name, source_read_error(exc))
            return
        if s["checkpoint"] is None and s["baseline_checkpoint"] is None and s["mode"] in {"new", "resume"} and not batch.lines and batch.bytes_read == 0:
            # If baseline persistence fails, retain this observation in memory;
            # later new records must not be skipped by repeatedly choosing EOF.
            s["baseline_checkpoint"] = copy.deepcopy(batch.checkpoint)
        events = []
        if s["read_error"]:
            events.append(self._synthetic(name, "Source readable again; coverage during unreadability was not guaranteed.", "info", "source-recovery", policy["recovery_notify"]))
        s["read_error"] = ""
        s["read_error_count"] = 0
        s["last_read"] = stamp()
        s["encoding"] = batch.encoding
        if batch.bytes_read:
            s["last_bytes"] = stamp()
        historical = s["historical"]
        if read_checkpoint is not None and (not isinstance(read_checkpoint, dict) or batch.checkpoint.get("generation") != read_checkpoint.get("generation")):
            self.context[name].clear()
            s["watch"].reset(now)
        for raw in batch.lines:
            event = self._record_event(name, raw, batch.checkpoint, historical)
            if event:
                events.append(event)
        for diagnostic in batch.diagnostics:
            log_level = logging.INFO if diagnostic.startswith("Encoding") or (batch.reset_recovered and "Oversized" not in diagnostic) else logging.WARNING
            self._diagnostic(f"{name.upper()}: {diagnostic}", level=log_level)
            if "gap" in diagnostic.lower() or "Oversized" in diagnostic:
                events.append(self._synthetic(name, diagnostic, "warning", "coverage"))
        if batch.reset_recovered:
            events.append(self._synthetic(name, "File save/replacement reconciled using complete records; only new records were processed. Changes before that boundary are outside new-entry monitoring.", "info", "source-change", notify=False))
        s["backlog"] = batch.backlog
        if batch.checkpoint.get("pending") or batch.checkpoint.get("discard"):
            if not s["incomplete_warned"] and now - s["incomplete_since"] >= max(60, policy["duration"]):
                events.append(self._synthetic(name, "Bytes received without a complete record; incomplete-line/parse health degraded.", "warning", "parse-health"))
                s["incomplete_warned"] = True
        else:
            s["incomplete_since"] = now
            s["incomplete_warned"] = False
        for incident in s["watch"].poll(now, success=True, new_bytes=batch.bytes_read, caught_up=batch.backlog == 0):
            events.append(self._synthetic(name, incident["message"], incident["severity"], incident["kind"], incident["notify"]))
        inserted = self._commit(name, batch.checkpoint, events)
        s["recent_errors"] += sum(e["severity"] in {"error", "critical"} for e in (inserted or []))
        s["state"] = "Storage degraded" if self.degraded else "Catching up" if batch.backlog else "Monitoring"
        if batch.backlog:
            s["next_check"] = now + .25  # one bounded batch per source per tick, fair catch-up
        elif s["historical"] and inserted is not None:
            s["historical"] = False
            self._diagnostic(f"{name.upper()}: historical review complete; subsequent records are live.")
            s["watch"].reset(now)

    def _read_failure(self, name, text):
        s = self.sources[name]
        s["state"] = "Waiting" if text.startswith("Waiting") else "Missing / Unreadable"
        s["read_error_count"] += 1
        if s["read_error"] != text:
            self._diagnostic(f"{name.upper()}: {text}")
            self._commit(name, None, [self._synthetic(name, text, "warning", "source-health", notify=False)])
        # Only persistent unreadability becomes externally eligible, separately from silence.
        if s["read_error_count"] == 3:
            self._commit(name, None, [self._synthetic(name, text + "; persists for three checks.", "warning", "source-health")])
        s["read_error"] = text

    def tick(self):
        now = self.clock()
        gap = now - self.last_tick
        self.last_tick = now
        try:
            self._collect_results()
        except (sqlite3.Error, OSError):
            self.degraded = True
            self._diagnostic("Outbox persistence unavailable; automatic dispatch paused. In-flight acceptance may be unknown.")
        if self.monitoring:
            if gap > max(30, 3 * self.config["poll_seconds"]):
                for name in self._enabled():
                    self.sources[name]["watch"].reset(now)
                    self._commit(name, None, [self._synthetic(name, f"Scheduling/sleep coverage gap: {gap:.0f} s. Reconciling data; fresh grace period.", "warning", "coverage")])
            if self.demo and now >= self.demo_next:
                self.demo.step()
                self.demo_next = now + 1
            for name in self._enabled():
                if now >= self.sources[name]["next_check"]:
                    self._poll(name)
        try:
            self._dispatch()
        except (sqlite3.Error, OSError):
            self.degraded = True
            self._diagnostic("Outbox unavailable; automatic dispatch paused.")
        if now - self.last_cleanup >= 60:
            self.last_cleanup = now
            try:
                if shutil.disk_usage(self.directory).free < 100 * 1024 * 1024:
                    self._diagnostic("Low state-disk space (<100 MiB). Checkpoint persistence and notification reliability may degrade.")
                count = self.store.cleanup(self.wall(), self.config["retention_days"], self.config["max_events"])
                if count >= self.config["max_events"]:
                    self._diagnostic("History capacity reached. Unacknowledged faults retained; acknowledge/export/delete history to restore capacity.")
                    self.degraded = True
                    self.capacity_blocked = True
                else:
                    self.capacity_blocked = False
            except (OSError, sqlite3.Error):
                self.degraded = True
                self._diagnostic("Storage maintenance failed; inspect available disk space and permissions.")

    def _payload(self, event):
        source = event["source"].upper()
        subject = f"ATLAS {'TEST' if self.demo else 'LIVE'} {source} {event['severity'].upper()} [{event['id']}]"
        label = f"Instrument: {self.config['instrument']}\nJob: {self.config['job'] or '(not set)'}"
        count = self.store.connection.execute("SELECT COUNT(*) FROM events WHERE source=? AND fingerprint=? AND receipt BETWEEN ? AND ?", (event["source"], event["fingerprint"], event.get("group_start", 0), event.get("group_end", 0))).fetchone()[0]
        body = f"{subject}\n{label}\nRules: {', '.join(event['rule_names'])}\nLogged level: {event['level']}\nSource timestamp (timezone not assumed): {event['timestamp_original']}\nDetected: {event['receipt_local']}\nFile: {Path(event['path']).name}\nOccurrences in window: {max(1,count)}\n\n{event['message']}"
        if self.config["include_paths"]:
            body += "\nFull source path: " + event["path"]
        if self.config["include_context"]:
            body += "\nPreceding context:\n" + "\n".join(event["context"])
        return subject, body

    def _dispatch(self):
        if not (self.monitoring and self.alerts and self.gate.is_set()) or self.degraded:
            return
        now = self.wall()
        for channel in self.transports:
            if channel in self.inflight or now < self.next_send[channel] or not self.config["channels"][channel]["enabled"]:
                continue
            row = self.store.ready(channel, self.monitor_session, self.alert_session, now)
            if row is None:
                continue
            event = self.store.event(row["event_id"])
            channel_config = copy.deepcopy(self.config["channels"][channel])
            secret = self.secret_store.get(channel_config["credential_ref"])
            subject, text = self._payload(event)
            gate = self.gate
            transport = self.transports[channel]
            recipient = row["recipient"]
            def send(transport=transport, cfg=channel_config, secret=secret, recipient=recipient, subject=subject, text=text, gate=gate):
                if not gate.is_set():
                    return DeliveryResult("suppressed", "Stopped before dispatch")
                return transport.send(cfg, secret, recipient, subject, text)
            self.store.outbox_status(row["id"], "sending", "Request in flight; stopping cannot retract provider acceptance", now)
            self.inflight[channel] = (dict(row), self.pools[channel].submit(send))
            self.channel_status[channel]["state"] = "Sending"
            self.next_send[channel] = now + self.config["channel_interval_seconds"]

    def _collect_results(self):
        for channel, (row, future) in list(self.inflight.items()):
            if not future.done():
                continue
            del self.inflight[channel]
            try:
                result = future.result()
            except Exception:
                result = DeliveryResult("unknown", "Unexpected channel worker failure; acceptance unknown")
            now = self.wall()
            status, due = result.status, None
            if status == "retry":
                active = self.monitoring and self.alerts and row["monitor_session"] == self.monitor_session and row["alert_session"] == self.alert_session
                if not active:
                    status = "suppressed"
                elif row["attempts"] >= 5:
                    status = "failed"
                else:
                    due = now + max(result.retry_after, min(300, 5 * 2 ** row["attempts"]) + random.uniform(0, 1))
            self.store.outbox_status(row["id"], status, self._redact(result.detail), now, due)
            self.channel_status[channel]["state"] = status
            if status == "accepted":
                self.channel_status[channel]["last_success"] = stamp()
                self.channel_status[channel]["last_error"] = ""
            else:
                self.channel_status[channel]["last_error"] = self._redact(result.detail)
        for job in list(self.jobs):
            channel, command, future = job
            if future.done():
                self.jobs.remove(job)
                try:
                    result = future.result()
                    if isinstance(result, DeliveryResult):
                        text = f"TEST {channel}: {result.status} — {result.detail}"
                        self.channel_status[channel]["state"] = result.status
                        if result.status == "accepted":
                            self.channel_status[channel]["last_success"] = stamp()
                            self.channel_status[channel]["last_error"] = ""
                        else:
                            self.channel_status[channel]["last_error"] = self._redact(result.detail)
                    else:
                        text = command + ": " + json.dumps(result, ensure_ascii=False)
                        # GUI can populate discovered chat candidates from snapshot without selecting one.
                        if command == "telegram_chats":
                            self.channel_status[channel]["chats"] = result
                        elif command == "gmail_check":
                            self.channel_status[channel]["connection_check"] = result
                    text = self._redact(text)
                    self.channel_status[channel]["test_result"] = text
                    success = result.status == "accepted" if isinstance(result, DeliveryResult) else isinstance(result, dict) and result.get("status") == "connection_ok"
                    self._diagnostic(text, level=logging.INFO if success else logging.WARNING)
                except Exception:
                    self.channel_status[channel]["test_result"] = "Setup/test failed; check credentials, network, chat permissions, and competing webhook/update consumer."
                    self._diagnostic(self.channel_status[channel]["test_result"])

    def handle(self, command: str, payload: dict | None = None):
        p = payload or {}
        if command == "configure":
            candidate = validate(p.get("config", p))
            safe_destination(self.directory, candidate, state=True)
            paths_changed = candidate["mode"] != self.config["mode"] or any(source_path(candidate, name).resolve() != source_path(self.config, name).resolve() or candidate["sources"][name]["encoding"] != self.config["sources"][name]["encoding"] for name in self.sources)
            if paths_changed and self.monitoring:
                self.handle("stop")
            channels_changed = candidate["channels"] != self.config["channels"]
            if channels_changed:
                self.store.suppress(alert=self.alert_session)
                self.alert_session = uuid.uuid4().hex
                self._new_gate()
            if not self.demo:
                self.config_store.save(candidate)
            self.config = candidate
            for name, s in self.sources.items():
                s["watch"].update_policy(copy.deepcopy(candidate["sources"][name]), self.clock())
                s["path"] = str(source_path(candidate, name).resolve())
                s["next_check"] = self.clock()
            return {"message": ("Demo settings applied in memory only." if self.demo else "Settings saved.") + " Rules apply to future batches." + (" Paths/mode changed: choose New / Review / Resume and start monitoring." if paths_changed else "")}
        if command == "start":
            mode = p.get("mode", "new")
            if mode not in {"new", "review", "resume"}:
                raise ValueError("Choose new, review or resume.")
            if self.monitoring:
                self.handle("stop")
            self.monitor_session = uuid.uuid4().hex
            self.history_offset = 0
            self.monitoring = True
            self.groups.clear()
            for name in self.sources:
                self._source_init(name, mode)
                self.sources[name]["historical_alerts"] = bool(p.get("historical_alerts", False))
                if name in self._enabled():
                    self.sources[name]["state"] = "Waiting"
            self._new_gate()
            return {"message": f"Monitoring started ({mode}). " + ("Historical alert sending explicitly enabled." if p.get("historical_alerts") else "Existing contents cannot send alerts in review mode.")}
        if command == "stop":
            self.monitoring = False
            self.gate.clear()
            self.store.suppress(monitor=self.monitor_session)
            for s in self.sources.values():
                s["state"] = "Stopped"
            return {"message": "Monitoring stopped. Unsent items suppressed; in-flight requests may still be accepted."}
        if command == "alerts":
            if self.demo and p.get("armed"):
                raise ValueError("Demo keeps automatic sending off. Use explicitly requested TEST buttons to test providers.")
            self.gate.clear()
            self.store.suppress(alert=self.alert_session)
            self.alerts = bool(p.get("armed", False))
            self.alert_session = uuid.uuid4().hex
            self._new_gate()
            return {"message": "External alerts armed for future eligible events." if self.alerts else "External alerts off; detection and history continue while monitoring."}
        if command == "acknowledge":
            self.store.acknowledge(p["id"])
            return {"message": "Acknowledged. History and active watch timers retained."}
        if command == "validate":
            name = p["source"]
            path = p.get("path", str(source_path(self.config, name).resolve()))
            try:
                batch = read_batch(path, start_mode="new", max_bytes=1, encoding=self.config["sources"][name]["encoding"])
            except (OSError, ValueError) as exc:
                raise ValueError(source_read_error(exc)) from None
            return {"message": f"Read-only access OK: {path}; {batch.encoding}; shared read/write/delete handle closed."}
        if command == "test_rule":
            record = parse_line(p["text"], p["source"])
            result = evaluate(self.config["rules"][p["source"]], record)
            return {"message": "Rule test only: " + json.dumps(result, ensure_ascii=False)}
        if command == "history":
            self.history_offset = max(0, int(p.get("offset", 0)))
            self.history_limit = min(1000, max(1, int(p.get("limit", 300))))
            return {"message": f"History offset {self.history_offset}"}
        if command == "clear_history":
            if self.monitoring or self.inflight:
                raise ValueError("Stop monitoring and wait for in-flight requests before deleting stored history.")
            with self.store.connection:
                self.store.connection.execute("DELETE FROM events")
            self.capacity_blocked = False
            self.degraded = False
            return {"message": "Stored history deleted; checkpoints retained."}
        if command == "export_history":
            return self._export(p)
        if command == "support_bundle":
            # Explicit request only; safe default omits local identifiers and scientific content.
            path = safe_destination(p["path"], self.config)
            config = portable_config(self.config)
            include_context = bool(p.get("include_context", False))
            if not include_context:
                config["instrument"] = config["job"] = "[REDACTED]"
                for source in config["sources"].values():
                    source["folder"] = "[REDACTED]"
                for channel in config["channels"].values():
                    for key in ["sender", "recipients", "chat_id"]:
                        if key in channel:
                            channel[key] = [] if key == "recipients" else "[REDACTED]"
            events = self.store.events(100)
            if not include_context:
                events = [{k: e.get(k) for k in ["id", "source", "level", "severity", "historical", "acknowledged", "kind"]} for e in events]
            bundle = dict(version=__version__, generated=stamp(), config=config, events=events,
                          diagnostics=list(self.diagnostics) if include_context else ["Detailed diagnostics omitted by privacy choice"],
                          degraded=self.degraded)
            path.write_text(self._redact(json.dumps(bundle, indent=2, ensure_ascii=False)), encoding="utf-8")
            return {"message": "Support bundle exported locally. Share it only with intended support personnel."}
        if command == "export_config":
            path = safe_destination(p["path"], self.config)
            path.write_text(json.dumps(portable_config(self.config), indent=2), encoding="utf-8")
            return {"message": "Secret-free configuration exported."}
        if command == "import_config":
            imported = portable_config(validate(json.loads(Path(p["path"]).read_text(encoding="utf-8"))))
            self.handle("stop")
            self.handle("alerts", {"armed": False})
            return self.handle("configure", imported)
        if command == "credential":
            channel = p["channel"]
            if channel not in self.transports:
                raise ValueError("Unknown channel")
            old = self.config["channels"][channel]["credential_ref"]
            if p.get("remove"):
                self.secret_store.delete(old)
                ref = ""
            else:
                if not p.get("secret", "").strip():
                    raise ValueError("Enter a secret before saving.")
                ref = self.secret_store.set(channel, p["secret"].strip(), p.get("persistent", True))
                if old and old != ref:
                    self.secret_store.delete(old)
            self.config["channels"][channel]["credential_ref"] = ref
            if self.demo and self.production_config:
                self.production_config["channels"][channel]["credential_ref"] = ref
                self.config_store.save(self.production_config)
            else:
                self.config_store.save(self.config)
            return {"message": "Credential removed." if not ref else "Credential is SESSION ONLY; re-enter after exit." if ref.startswith("session:") else "Credential saved in Windows Credential Manager."}
        if command in {"test_channel", "telegram_check", "telegram_chats", "gmail_check"}:
            return self._setup_job(command, p)
        if command in {"discard_queue", "replay_queue"}:
            return self._queue_action(command, p)
        if command == "demo":
            action = p.get("action", "start")
            if action == "stop":
                self.handle("stop")
                self.handle("alerts", {"armed": False})
                if self.production_config:
                    self.config = self.production_config
                self.production_config = None
                self.demo = None
                for name in self.sources:
                    self._source_init(name, "new")
                return {"message": "Demo stopped; original source configuration restored. Monitoring and alerts off."}
            if action == "start":
                self.handle("stop")
                self.handle("alerts", {"armed": False})
                if self.production_config is None:
                    self.production_config = copy.deepcopy(self.config)
                self.demo = DemoWriter(self.directory / "demo" / uuid.uuid4().hex)
                config = copy.deepcopy(self.config)
                config["mode"], config["poll_seconds"] = "both", 1
                for name, path in self.demo.paths.items():
                    config["sources"][name]["folder"] = str(path.parent)
                    config["sources"][name]["filename"] = path.name
                # Demo setup stays in memory and cannot replace the user's saved production paths.
                self.config = config
                self.handle("start", {"mode": "new"})
                return {"message": "DEMO — simulated files only. External alerts disabled. Test buttons send TEST messages only when requested."}
            if not self.demo:
                raise ValueError("Start the demo first.")
            if action in {"pause", "resume"}:
                self.demo.paused = action == "pause"
            elif action in {"rotate", "truncate", "burst"}:
                self.demo.mutate(action)
            return {"message": f"DEMO {action}"}
        raise ValueError("Unknown command")

    def _setup_job(self, command, p):
        channel = p.get("channel", "gmail" if command == "gmail_check" else "telegram")
        if channel not in self.transports:
            raise ValueError("Unknown channel")
        if sum(j[0] == channel for j in self.jobs) >= 3:
            raise ValueError("A setup action is already pending; wait for its result.")
        config = copy.deepcopy(self.config["channels"][channel])
        if command == "gmail_check":
            if channel != "gmail":
                raise ValueError("SMTP connectivity check applies to Gmail only.")
            future = self.pools[channel].submit(self.transports[channel].check_connection, config)
            self.jobs.append((channel, command, future))
            return {"message": "SMTP connection check pending; no authentication or email sending. Automatic controls unchanged."}
        secret = self.secret_store.get(config["credential_ref"])
        if not secret:
            raise ValueError("Save a credential first (secure storage or session only).")
        transport = self.transports[channel]
        if command == "telegram_check":
            future = self.pools[channel].submit(transport.get_me, secret)
        elif command == "telegram_chats":
            future = self.pools[channel].submit(transport.find_chats, secret)
        else:
            recipients = config["recipients"] if channel == "gmail" else [config["chat_id"]] if config["chat_id"] else []
            if not recipients:
                raise ValueError("Enter recipient(s) / chat ID before testing.")
            def test():
                outcomes = [transport.send(config, secret, recipient, "ATLAS TEST — requested channel test", f"TEST from {self.config['instrument']} at {stamp()}. Verify receipt and phone notification settings.") for recipient in recipients]
                status = "accepted" if all(o.status == "accepted" for o in outcomes) else "unknown" if any(o.status == "unknown" for o in outcomes) else "failed" if any(o.status == "failed" for o in outcomes) else "retry"
                detail = "; ".join(f"Recipient {i+1}: {o.status} {o.detail}" for i, o in enumerate(outcomes))
                if status != "accepted":
                    detail += " TEST requests are not automatically resent; retry explicitly after checking the result."
                return DeliveryResult(status, detail)
            future = self.pools[channel].submit(test)
        self.jobs.append((channel, command, future))
        return {"message": f"{command} pending in {channel} worker; automatic controls unchanged."}

    def _queue_action(self, command, p):
        selected = p.get("ids", [])
        if command == "replay_queue" and not (self.monitoring and self.alerts):
            raise ValueError("Deliberate resend requires monitoring and alerts armed. This action can send old events.")
        with self.store.connection:
            where = "(status IN ('failed','unknown','suppressed') OR (status='cancelled' AND detail!='Deliberately discarded'))"
            args = []
            if selected:
                where += " AND event_id IN (" + ",".join("?" for _ in selected) + ")"
                args.extend(selected)
            if command == "discard_queue":
                self.store.connection.execute("UPDATE outbox SET status='cancelled',detail='Deliberately discarded' WHERE " + where, args)
            else:
                self.store.connection.execute("UPDATE outbox SET status='pending',monitor_session=?,alert_session=?,due=?,attempts=0,detail='Deliberate resend' WHERE " + where,
                                              [self.monitor_session, self.alert_session, self.wall()] + args)
        return {"message": "Explicit queue action applied. Unknown acceptance may produce duplicate external messages if resent."}

    def _export(self, p):
        path = safe_destination(p["path"], self.config)
        context = bool(p.get("include_context", False))
        fmt = p.get("format", "json")
        fields = ["id", "source", "level", "severity", "rule_names", "timestamp_original", "receipt_local", "receipt_utc", "message", "count", "acknowledged", "historical", "deliveries"]
        if context:
            fields += ["path", "context", "raw_line", "raw_b64", "diagnostic"]
        with path.open("w", encoding="utf-8", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=fields) if fmt == "csv" else None
            if writer:
                writer.writeheader()
            else:
                out.write("[\n")
            offset = 0
            first = True
            while True:
                batch = self.store.events(500, offset)
                if not batch:
                    break
                for event in batch:
                    row = {f: event.get(f, "") for f in fields}
                    if writer:
                        writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
                    else:
                        if not first:
                            out.write(",\n")
                        json.dump(row, out, ensure_ascii=False)
                    first = False
                offset += len(batch)
            if not writer:
                out.write("\n]\n")
        return {"message": f"History exported to {path}. Scientific messages may identify experiments."}

    def snapshot(self):
        now = self.clock()
        sources = {}
        for name, s in self.sources.items():
            sources[name] = {k: v for k, v in s.items() if k not in {"checkpoint", "baseline_checkpoint", "watch"}}
            watch = s["watch"]
            interval = self.config["sources"][name]["interval"] or self.config["poll_seconds"]
            sources[name].update(quiet_seconds=max(0, now-watch.last_bytes), empty_cycles=watch.empty_cycles,
                                 watch_status=watch.status(now), next_check=max(0, s["next_check"]-now), effective_interval=interval,
                                 threshold=self.config["sources"][name]["cycles"] * interval if self.config["sources"][name]["inactivity_mode"] == "cycles" else self.config["sources"][name]["duration"])
        try:
            events = self.store.events(self.history_limit, self.history_offset)
            pending_count = self.store.pending_count()
        except sqlite3.Error:
            events = []
            pending_count = 0
            self.degraded = True
        return dict(config=copy.deepcopy(self.config), monitoring=self.monitoring, alerts=self.alerts, monitor_session=self.monitor_session,
                    sources=sources, events=list(reversed(self.emergency)) + events, live={c: list(v) for c, v in self.live.items()},
                    diagnostics=list(self.diagnostics), pending_count=pending_count, channel_status=copy.deepcopy(self.channel_status),
                    degraded=self.degraded, demo=self.demo is not None, secure_store=self.secret_store.available)

    def close(self):
        self.handle("stop")
        self.gate.clear()
        for pool in self.pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
        # Persist any already-completed requests honestly before releasing the DB.
        self._collect_results()
        self.store.close()
        for handler in list(self.log.handlers):
            handler.close()
            self.log.removeHandler(handler)
