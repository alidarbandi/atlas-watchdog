# Developer architecture

The GUI uses PySide6/Qt Widgets, not an embedded browser. Widgets belong to the Qt GUI thread. A worker owns the controller, file polling, parsing batches, rules, activity state and SQLite connection; queued commands/results cross the thread boundary. Provider calls run in independent channel workers so a blocked Gmail request does not block Telegram, source reads or widget event handling. A per-user crash-safe single-instance mechanism avoids duplicate readers and notifications.

| Module | Responsibility |
|---|---|
| `file_access.py` | Narrow ctypes Windows API declarations, read-only share flags, handle metadata, bounded seeks/reads and deterministic close. A POSIX read-only fallback supports development tests without asserting Windows equivalence. |
| `tailer.py` | Immutable-input serializable byte checkpoints, BOM/encoding selection, newline framing, bounded record/discard state, identity/boundary resets and backlog. |
| `parser.py` | Explicit day-first timestamp parsing, original/raw preservation, level normalization, receipt times and diagnostics. |
| `rules.py` | Source-specific literal/level matching, Unicode boundary semantics, explicit ignores, highest severity and combined channel/rule evidence. |
| `activity.py` | Injected monotonic activity/heartbeat/progress clocks, grace/lifecycle pause, incidents/reminders/recovery. |
| `storage.py` | Single-owner SQLite WAL/FULL transactions, event/checkpoint/outbox coherence, recipient status, attempt history and protective retention. |
| `notifications.py` | Gmail verified TLS and plain Telegram HTTPS transports, bounded timeouts, setup discovery and sanitized provider results. No hidden transport retry loop. |
| `secrets.py` | Typed Windows Credential Manager APIs with per-user app namespace, deterministic free and disclosed in-memory session fallback. |
| `config.py` | Versioned defaults/schema, validation, atomic previous-copy replacement, secret-free portability and destination protection. |
| `controller.py` | Source sessions, polling boundaries, delivery eligibility, worker scheduling, storage failure behavior and command/snapshot interface. |
| `gui.py` | Native controls, source cards/rules/live history/setup, safe queued worker interaction and tray lifecycle. |
| `demo.py` | Dedicated sanitized simulator/replay files, with external sends off by default. |

The exact core interfaces are `read_batch(path, checkpoint, start_mode, encoding, ...) -> TailBatch` and `parse_line(text, source, raw_b64, diagnostic, source_timezone) -> dict`. A `RawLine` includes absolute start/end offsets, text, base64 bytes and a diagnostic. The checkpoint scheme is read-cursor plus pending bytes/discard state; do not substitute a complete-line-only cursor without changing transaction/resume tests.

Source handles must never survive into parser, database, GUI or network work. Each batch snapshots its open-handle end and bounds bytes; future polls attempt a read even if directory metadata is unchanged. Rule changes are applied at future batch boundaries. Event identity uses source/generation/offset so reprocessing a committed suffix cannot create a second event. Source-local context is bounded and collected during streaming rather than rereading a whole file.

Tests use temporary simulated writers, injected clocks and mocked provider transports. Windows-only integration tests explicitly cover shared writer access, exact requested flags and exclusive-reopen conflicts. Actual sample logs are read-only references; sanitized fixtures are used for repository tests and release/demo assets. Tests do not contact real recipients.

Use [Qt's QThread/signals guidance](https://doc.qt.io/qtforpython-6.8/PySide6/QtCore/QThread.html) when adding background work. Keep the SQLite connection in its owner thread; channel threads return sanitized values and never call widgets or share the connection. Add timeouts and session checks to any future provider. Do not add remote commands, unrestricted regex, source writes, long-lived handles or automatic stale-queue replay.
