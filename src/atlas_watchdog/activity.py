"""Independent monotonic activity, heartbeat, progress, and lifecycle watches."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ActivityWatch:
    policy: dict
    started: float
    last_bytes: float = 0
    last_record: float = 0
    last_heartbeat: float = 0
    last_progress: float = 0
    empty_cycles: int = 0
    progress_values: dict = field(default_factory=dict)
    incidents: dict = field(default_factory=dict)
    lifecycle_paused: bool = False

    def __post_init__(self):
        self.reset(self.started)

    def reset(self, now):
        self.started = self.last_bytes = self.last_record = self.last_heartbeat = self.last_progress = now
        self.empty_cycles = 0
        self.incidents.clear()
        self.lifecycle_paused = False

    def update_policy(self, policy, now):
        old = self.policy
        self.policy = policy
        if any(old.get(x) != policy.get(x) for x in ["expect_activity", "heartbeat", "progress"]):
            self.reset(now)

    def record(self, record: dict, now: float):
        self.last_record = now
        message = record["message"]
        if "Process is alive." in message:
            self.last_heartbeat = now
        progress = False
        # Completion evidence is preferred. Repeated acquisition starts alone do not count.
        if "Image completed" in message:
            progress = True
        for field, value in re.findall(r"\b(ImageNo|MillZ)\s*[:=]\s*(-?\d+(?:\.\d+)?)", message, re.I):
            field = field.casefold()
            numeric = float(value)
            if field in self.progress_values and numeric > self.progress_values[field]:
                progress = True
            self.progress_values[field] = numeric
        if progress:
            self.last_progress = now
        lifecycle = any(x in message for x in ["Run Ended.", "End of execute process", "Atlas 3D application has been suspended."])
        if lifecycle and self.policy.get("lifecycle_disarm"):
            self.lifecycle_paused = True
        return lifecycle

    def poll(self, now: float, *, success: bool, new_bytes: int, caught_up=True) -> list[dict]:
        if not success:
            # Unreadability is handled by source health, never counted as an empty cycle.
            return []
        if new_bytes:
            self.last_bytes = now
            self.empty_cycles = 0
        elif caught_up:
            self.empty_cycles += 1
        policy = self.policy
        if not policy["expect_activity"] or self.lifecycle_paused or not caught_up or now - self.started < policy["grace"]:
            return []
        quiet = now - self.last_bytes
        triggers = {"silence": (self.empty_cycles >= policy["cycles"] if policy["inactivity_mode"] == "cycles" else quiet >= policy["duration"]) and not new_bytes,
                    "heartbeat": policy["heartbeat"] and now - self.last_heartbeat >= policy["heartbeat_seconds"],
                    "progress": policy["progress"] and now - self.last_progress >= policy["progress_seconds"]}
        results = []
        for kind, triggered in triggers.items():
            elapsed = quiet if kind == "silence" else now - getattr(self, "last_" + kind)
            if triggered:
                previous = self.incidents.get(kind)
                reminder = policy.get("reminder_seconds", 0)
                if previous is None or (reminder and now - previous >= reminder):
                    self.incidents[kind] = now
                    wording = {"silence": "No new log activity — possible stalled acquisition",
                               "heartbeat": "No execution heartbeat observed — possible stalled acquisition",
                               "progress": "No imaging progress observed — heartbeat alone does not prove progress"}[kind]
                    results.append(dict(kind=kind, message=f"{wording}. Quiet for {elapsed:.1f} s; successful empty cycles: {self.empty_cycles}.",
                                        severity="warning", notify=True, reminder=previous is not None))
            elif kind in self.incidents:
                self.incidents.pop(kind)
                results.append(dict(kind=kind + "-recovery", message=f"Observed {kind} activity resumed.", severity="info",
                                    notify=policy.get("recovery_notify", False), reminder=False))
        return results

    def status(self, now):
        if not self.policy["expect_activity"]:
            return "Not armed — keyword monitoring only"
        if self.lifecycle_paused:
            return "Paused by lifecycle phrase; run ended (success not inferred)"
        if now - self.started < self.policy["grace"]:
            return f"Startup/resume grace: {self.policy['grace'] - (now-self.started):.0f} s"
        return "Incident: " + ", ".join(self.incidents) if self.incidents else "Armed — observing expected activity"
