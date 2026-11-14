# Source format and sample observations

The exact observed engine header `Application log` and blank separator lines remain visible without generating parse-health warnings. Only that known engine header receives this exception; malformed text containing possible errors still carries a diagnostic, and reader/decode warnings are retained. Preceding context resets for each new monitoring session and source-file generation.

Each timestamped ATLAS record uses tab-separated date, time, level, component and message. Extra tab separators before the message are accepted; tabs inside the message are retained. Lines normally end in Windows CRLF. Dates are explicitly parsed as **day/month/year** and millisecond time, while the original timestamp text is preserved.

The source timezone is unknown by default. Parsed source times remain naive, never mislabeled UTC. An optional IANA timezone such as `America/Toronto` can be selected per source. Receipt time is recorded separately as local ISO time with an offset and unambiguous UTC. Activity thresholds use runtime monotonic time, not either timestamp.

Known levels are case-insensitive Trace, Debug, Log, Info, Warning/Warn, Error, Fatal and Critical. Unknown values stay visible. Malformed lines retain their original text as the message and carry diagnostics; parsing failure does not silently hide a possible error.

## Byte and encoding policy

The tailer tracks byte offsets and persists its read cursor **together with** pending bytes, partial-record start, encoding, generation, boundary hash and discard state. The controller commits that complete checkpoint transactionally with events/outbox records. Crash recovery rereads from the last committed state, without advancing beyond unrecorded events.

Auto encoding checks a UTF-8 or UTF-16 BOM. Without a BOM, each complete 8-bit record is decoded with strict UTF-8 first, then CP1252 on failure. The source encoding label is `auto-8bit` for this policy; a fallback diagnostic accompanies affected records. Explicit UTF-8, CP1252 or UTF-16 endian overrides are available. Undefined/invalid sequences use escaped bytes; every retained record includes base64 raw bytes for lossless inspection. Split code points, CRLF and UTF-16 newline units remain buffered across reads and restarts.

A normal read budget is 256 KiB and at most 2,048 framed records per source batch. Byte framing leaves extra complete records in the source for the next fair batch rather than growing a checkpoint. The source handle closes before decoding/parsing/storage/notification work. The handle's captured end position bounds each batch even if a writer keeps appending. The maximum record length defaults to 64 KiB: an oversized line emits a diagnostic with its bounded raw prefix, then discards through the next aligned newline and resumes. The complete oversized line is not retained. Backlog and resynchronization are visible.

Windows identity uses volume serial plus file index. A 64-byte cursor-boundary hash supplements handle size to detect a same-file rewrite near the cursor. This cannot discover every arbitrary overwrite earlier in a file; unrecoverable overwritten bytes remain a limit. Same-size/larger pathname replacement is detected by identity. Replacement/truncation/rewrite creates a new generation and a possible coverage-gap event. No filename rotation convention is configured in this version, so unread tails of renamed old files are not guaranteed drained. A whole file created and removed between polls is unobservable.

For ongoing new-entry monitoring, the checkpoint also retains at most 4 KiB of cursor-anchor bytes. After a reset, a separate bounded read of at most 64 KiB from the rewritten tail is searched for one unique anchor; supported encoding/CRLF conversions are considered after the source handle closes. Only records after that verified boundary become new records, with unfinished-record handling as described below. Missing, repeated, incompatible, or distant context causes a fresh EOF baseline and an explicit coverage warning, never an automatic historical replay. These auxiliary reads are bounded in addition to the normal payload budget. A crash before the event/checkpoint transaction commits rereads the previous checkpoint consistently.

From v0.1.4, recovery compares complete records in the anchor rather than requiring an exact match of trailing blank bytes. Blank separator removal, added records before trailing blanks, and CRLF/LF changes are handled without replaying old records. A live unfinished record can complete after a save; an unfinished record that already existed at the initial baseline is still discarded through its completion. Historical partial text must match its retained prefix before it can be safely skipped. Record comparisons are bounded to 4,096 frames per recovery window. Missing, repeated, changed historical, or distant context still produces a coverage warning; arbitrary edits cannot always be classified as new appends.

## The two supplied reference files

The original logs were read only. They are not live paths, test writers, release assets or configuration defaults.

| Sample | Measured timestamped records | Levels |
|---|---:|---|
| Engine export | 1,313 | 1,239 Log; 74 Info; no Error |
| Execution export | 19,684 | 17,704 Trace; 1,052 Info; 580 Log; 327 Debug; 15 Warning; 6 Error |

The engine's `Application log` header is retained separately as an unstructured diagnostic record. CP1252 fallback was needed for 353 engine and 5,327 execution records in the reader verification run.

Engine candidate `WMAcqError WP=8 r=False` is logged at Log level; `Failed to assign detector "InLens" to output 0` is Info. Their operational meaning needs user/vendor validation. Hardware enumeration can include “communication failed: device may not be populated”; generic failure words are therefore noisy. No interpretation of WP=8 is invented.

Execution errors include microscope/connection nonresponse, beam-shift failures with “Unable to recover”/“Stopping acquisition”, and a blanked-beam image grab. The historical rename-warning already existed in the supplied sample and was not caused by this watchdog.

The observed EHT phrase is `Turning SEM EHT off`. The separate user-requested `Turning EHT OFF` preset does not match the extra word automatically. Both are offered explicitly and start unchecked, as does the unverified standby phrase. The sample's `Run Ended.` follows acquisition errors; lifecycle labels deliberately avoid declaring success.
