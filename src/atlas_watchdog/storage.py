"""One-thread-owned SQLite history, checkpoints and durable recipient outbox."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


class Store:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path, timeout=3)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise ValueError("Unsupported state schema; preserve the database and use the matching application version.")
        self.connection.executescript("""
          CREATE TABLE IF NOT EXISTS checkpoints(source TEXT PRIMARY KEY, path TEXT NOT NULL, data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, source TEXT NOT NULL, receipt REAL NOT NULL,
            message TEXT NOT NULL, severity TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0,
            fingerprint TEXT NOT NULL, data TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS events_time ON events(receipt DESC);
          CREATE INDEX IF NOT EXISTS events_group ON events(source,fingerprint,receipt DESC);
          CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            channel TEXT NOT NULL, recipient TEXT NOT NULL, status TEXT NOT NULL, monitor_session TEXT NOT NULL,
            alert_session TEXT NOT NULL, due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            detail TEXT NOT NULL DEFAULT '', updated REAL NOT NULL, UNIQUE(event_id,channel,recipient));
          CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, outbox_id INTEGER NOT NULL REFERENCES outbox(id) ON DELETE CASCADE,
            stamp REAL NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL);
          PRAGMA user_version=1;
        """)
        # A process crash during a network request cannot establish provider acceptance.
        with self.connection:
            self.connection.execute("UPDATE outbox SET status='unknown',detail='Process ended during send; acceptance unknown' WHERE status='sending'")
            self.connection.execute("UPDATE outbox SET status='cancelled',detail='Previous process/session; deliberate resend required' WHERE status IN ('pending','retry')")

    def checkpoint(self, source, path):
        row = self.connection.execute("SELECT data FROM checkpoints WHERE source=? AND path=?", (source, path)).fetchone()
        if not row:
            return None
        try:
            value = json.loads(row[0])
            return {"invalid_checkpoint": True} if value is None else value
        except (ValueError, TypeError):
            # The tailer validates and visibly resets this sentinel checkpoint.
            return {"invalid_checkpoint": True}

    def commit_batch(self, source, path, checkpoint, events, recipients, sessions, eligible, now, max_outbox=10000):
        inserted = []
        with self.connection:
            for event in events:
                cursor = self.connection.execute("INSERT OR IGNORE INTO events(id,source,receipt,message,severity,fingerprint,data) VALUES(?,?,?,?,?,?,?)",
                        (event["id"], source, now, event["message"], event["severity"], event["fingerprint"], json.dumps(event, ensure_ascii=False)))
                if not cursor.rowcount:
                    continue
                inserted.append(event)
                for channel in event.get("channels", []):
                    for recipient in recipients.get(channel, []):
                        status = "pending" if eligible and event.get("notify", True) else "suppressed"
                        count = self.connection.execute("SELECT COUNT(*) FROM outbox WHERE status IN ('pending','retry','sending')").fetchone()[0]
                        detail = "" if status == "pending" else "Automatic sending off or historical review"
                        due = now
                        followup = event.get("group_followup", "")
                        if followup and followup != event["id"]:
                            status, detail = "suppressed", f"Grouped in follow-up event {followup}; raw occurrence retained"
                        elif followup:
                            due = event["group_end"]
                            detail = "Burst follow-up digest waiting for grouping window"
                        if status == "pending" and count >= max_outbox:
                            status, detail = "failed", "Queue capacity reached — event retained; explicit resend available"
                        self.connection.execute("INSERT INTO outbox(event_id,channel,recipient,status,monitor_session,alert_session,due,updated,detail) VALUES(?,?,?,?,?,?,?,?,?)",
                            (event["id"], channel, recipient, status, sessions[0], sessions[1], due, now, detail))
            if checkpoint is not None:
                self.connection.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)", (source, path, json.dumps(checkpoint)))
        return inserted

    def events(self, limit=300, offset=0):
        rows = self.connection.execute("SELECT * FROM events ORDER BY receipt DESC,rowid DESC LIMIT ? OFFSET ?", (min(limit, 1000), offset)).fetchall()
        result = []
        for row in rows:
            event = json.loads(row["data"])
            event["acknowledged"] = bool(row["acknowledged"])
            deliveries = {}
            attempts = []
            for delivery in self.connection.execute("SELECT * FROM outbox WHERE event_id=?", (row["id"],)):
                deliveries.setdefault(delivery["channel"], []).append(f"{delivery['recipient']}: {delivery['status']} ({delivery['detail']})")
                detail = dict(delivery)
                detail["history"] = [dict(x) for x in self.connection.execute("SELECT stamp,status,detail FROM attempts WHERE outbox_id=? ORDER BY id DESC LIMIT 30", (delivery["id"],))]
                attempts.append(detail)
            event["deliveries"] = {key: "; ".join(value) for key, value in deliveries.items()}
            event["attempts"] = attempts
            count = self.connection.execute("SELECT COUNT(*) FROM events WHERE source=? AND fingerprint=? AND receipt BETWEEN ? AND ?",
                     (row["source"], row["fingerprint"], event.get("group_start", row["receipt"]), event.get("group_end", row["receipt"]))).fetchone()[0]
            event["count"] = max(1, count)
            result.append(event)
        return result

    def suppress(self, monitor=None, alert=None):
        query = "UPDATE outbox SET status='suppressed',detail='Stopped; future events only on rearm' WHERE status IN ('pending','retry')"
        args = []
        if monitor is not None:
            query += " AND monitor_session=?"
            args.append(monitor)
        if alert is not None:
            query += " AND alert_session=?"
            args.append(alert)
        with self.connection:
            self.connection.execute(query, args)

    def ready(self, channel, monitor, alert, now):
        return self.connection.execute("SELECT * FROM outbox WHERE channel=? AND monitor_session=? AND alert_session=? AND status IN ('pending','retry') AND due<=? ORDER BY id LIMIT 1", (channel, monitor, alert, now)).fetchone()

    def outbox_status(self, item_id, status, detail, now, due=None):
        with self.connection:
            self.connection.execute("UPDATE outbox SET status=?,detail=?,updated=?,due=COALESCE(?,due),attempts=attempts+? WHERE id=?", (status, detail, now, due, int(status == "sending"), item_id))
            self.connection.execute("INSERT INTO attempts(outbox_id,stamp,status,detail) VALUES(?,?,?,?)", (item_id, now, status, detail))

    def event(self, event_id):
        row = self.connection.execute("SELECT data FROM events WHERE id=?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def acknowledge(self, event_id):
        with self.connection:
            self.connection.execute("UPDATE events SET acknowledged=1 WHERE id=?", (event_id,))

    def pending_count(self):
        return self.connection.execute("SELECT COUNT(*) FROM outbox WHERE status IN ('pending','retry','failed','unknown') OR (status='cancelled' AND detail!='Deliberately discarded')").fetchone()[0]

    def cleanup(self, now, days, max_events):
        cutoff = now - days * 86400
        # Unacknowledged faults and unresolved deliveries are preserved. Report inability to reach cap.
        with self.connection:
            unresolved = "SELECT event_id FROM outbox WHERE status IN ('pending','sending','retry','failed','unknown') OR (status='cancelled' AND detail!='Deliberately discarded')"
            self.connection.execute("DELETE FROM events WHERE acknowledged=1 AND receipt<? AND id NOT IN (" + unresolved + ")", (cutoff,))
            self.connection.execute("DELETE FROM events WHERE id IN (SELECT id FROM events ORDER BY receipt DESC LIMIT -1 OFFSET ?) AND acknowledged=1 AND id NOT IN (" + unresolved + ")", (max_events,))
        return self.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self):
        self.connection.close()
