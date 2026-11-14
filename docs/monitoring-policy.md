# Monitoring, alert and timing policy

## Two independent controls

| Monitoring | External alerts | Behavior |
|---|---|---|
| Stopped | Off | No polling and no automatic sends. |
| Stopped | Armed | Alerts wait for monitoring; no automatic sends. |
| Running | Off | Read, detect, store and display; outgoing work is suppressed. |
| Running | Armed | Read/detect and send eligible events through enabled configured channels. |

Both controls start off after launch. Preferences persist without silently restoring alert sending. There are no hidden startup tasks or installer changes. Test buttons send only the requested TEST through the selected configured channel; they do not change either control.

Each monitoring activation and alert arming has its own session ID. Stopping either control suppresses unsent work for that session; stopping monitoring may leave the alert switch armed for a future monitoring session. Rearming accepts future eligible events only. Old pending/retry rows from a previous process become cancelled, and interrupted Sending rows become Unknown acceptance. Persisted undelivered items require deliberate resend or discard. An in-flight provider request cannot be recalled; its real eventual status remains visible.

## Source sessions and history

ENGINE and EXECUTION have independent paths, checkpoints, rules, schedules and health/activity states. One unreadable source does not suspend the other. Engine bytes never reset execution timers.

**New entries only** establishes a read-handle EOF baseline. If it ends in a historical partial line, the remainder is discarded through its eventual newline; later records are new. On rewrite/replacement/truncation, an ongoing new-entry session does **not** replay the file from the beginning. It tries to locate a unique retained cursor anchor in the rewritten tail, including supported encoding changes, then processes only the following bytes. If the anchor is missing or ambiguous, it establishes a fresh EOF baseline and reports a coverage gap: records written during that rewrite may be missed, but earlier errors are not replayed. Future appends are monitored normally.

**Review existing contents** deliberately processes history with external alerts suppressed. Historical sending requires an explicit historical-alert choice. **Resume** validates the saved file identity, cursor and boundary; its initial backlog is marked historical and suppressed until catch-up finishes unless historical alerts were explicitly allowed. Invalid checkpoints during an explicit initial historical review/resume can read the new generation from its beginning, with a coverage diagnostic. After catch-up, the ongoing observation uses the new-entry rewrite policy above. Restarting monitoring or resuming does not authorize an old notification queue.

**Current session only** is checked by default in Events & history. It hides events from previous monitoring sessions without deleting stored history. Starting monitoring resets pagination and returns to this view. Uncheck it, or choose Older history, to inspect past events.

Rule changes apply at the next processing boundary to future records, without rescan/resend. Path/mode changes require a clean source-session restart and explicit start policy. Timing changes apply without an app restart. Error-level logs and assigned alert severity remain distinct. Multiple matching rules produce one source-record event with all matching rule IDs and the highest assigned severity. Ignore matches are auditable and can suppress an Error-level record only under an explicit configured rule.

Whole-word matching uses Unicode letters/digits/underscore (`\w`) as word characters. The complete literal phrase must have no such character immediately before or after it; punctuation is a boundary. Exact-message matches compare the complete selected message/full line. Case-insensitive matching uses Unicode case folding. No user-supplied regular expressions are evaluated.

## Activity, heartbeat and progress

Expect activity is deliberate and per source. Keyword monitoring can run while it is unarmed; the UI says so. A successful read with no new bytes increments the source's consecutive empty scheduled-poll count. New bytes reset that count and byte-activity time. Failed reads, disabled sources and stopped monitoring are not empty successful polls. Read health and quietness are separate.

In cycles mode, threshold N and effective interval T give a **nominal N × T** silence window. Real elapsed time is shown because disk and scheduling delays make the count approximate. Duration mode waits until a healthy read confirms no bytes after the configured monotonic interval. Startup and manual rearming receive a grace period; old log timestamps do not instantly create silence alarms. Backlog reconciliation does not pretend the source has been observed continuously or is quiet.

The wording is **No new log activity — possible stalled acquisition**. Silence is evidence of no observed bytes, not proof that ATLAS or Windows crashed. Engine activity checks default unarmed; the sample later emits roughly hourly temperature records. Execution's editable starting preset is 30 cycles, nominally 300 seconds at 10-second polling. These are sample-based defaults, not vendor specifications.

The optional execution heartbeat watch recognizes `Process is alive.` with a starting 300-second threshold. The sample's 83 heartbeat records have gaps of about 121–187 seconds. Progress is separate: image completion or advancing observed `ImageNo`/`MillZ` values can count; repeated acquisition starts and unchanged heartbeat values do not establish successful imaging. Measurements retain their scientific context without invented completion percentages. Configure generous thresholds around autofocus, milling and long operations.

Expect-activity pause leaves keyword monitoring on; resume/rearming begins a new grace window. With lifecycle disarm enabled, `Run Ended.`, `End of execute process`, or `Atlas 3D application has been suspended.` pauses the activity watches and records a lifecycle event. Run Ended is never proof of successful completion. Earlier faults stay visible and selectable EHT/standby rules can still match.

One incident per watch persists until observed activity resumes. Acknowledgment alone does not reset the timer or resolve an outage. Optional recovery notifications and configurable reminders are separate, rate-limited events. Bytes, complete records, parsed progress and read health are tracked separately; continuous partial garbage does not establish imaging progress. Sleep/major scheduling gaps produce coverage warnings and a new grace interval on reconciliation.

## Delivery and retention

The event/checkpoint/outbox transaction completes before any network call. Gmail and Telegram workers are independent of one another and source reads. Outbox entries are per channel and recipient. Accepted work is not retried because another channel/recipient failed. Retry requires the same active eligible monitor/alert session; exponential backoff is bounded, and Telegram's supplied delay is honored. Unknown acceptance is held for an explicit user decision because exactly-once delivery cannot be guaranteed after network uncertainty. Stable source-generation/record-offset event IDs help recognize duplicate submissions.

The first matching event is immediately visible and eligible. Within the configured grouping window, the second equivalent occurrence schedules one follow-up digest for the end of that window; further repeats remain stored but their external work is grouped into that digest. Numeric values and differing messages are retained. Group counts do not erase raw occurrences. Provider rate limits may delay outgoing work; new distinct faults remain visible.

The GUI keeps bounded rows and requests older SQLite pages. Default history targets are 90 days and 50,000 events, and the pending outbox is bounded. Unacknowledged faults and unresolved deliveries are protected. At event capacity, checkpoint advancement and automatic dispatch pause; only the latest 100 emergency events are kept in memory, with a visible degraded-reliability warning. Disk/database failures also hold checkpoint advancement. Export, acknowledge, or delete history and restore writable storage promptly while the source generations remain available; overwritten or removed source data may be unrecoverable.

Local event history can contain experiment data. Paths and extra preceding context are opt-in in outgoing payloads; whole logs are never automatically attached. Config exports omit secrets/references; raw scientific context in history exports is deliberate. Acknowledgment preserves history. Clearing the display and deleting stored history are different actions; deletion requires an explicit workflow.
