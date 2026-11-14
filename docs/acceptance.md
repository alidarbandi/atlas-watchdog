# Workstation acceptance checklist

Automated tests and development packaging are useful evidence, but are not microscope acceptance. Perform these checks on the actual supported Windows build, or a representative clean VM where appropriate, before unattended acquisition. Use an expendable experiment and a normal non-admin user. Record date, OS build, executable SHA256, app version and results.

## Clean packaged application

- Run both the diagnostic one-folder and portable one-file forms on Windows x64 **without Python installed**. Confirm required Qt DLLs/platform plugins and CA/timezone data are present, launch has no release console window, UI remains responsive and normal scaling/keyboard navigation works.
- Confirm durable state goes to `%LOCALAPPDATA%\ATLASWatchdog`, survives moving/restarting the EXE and never appears in `_MEI…`, the executable directory, source folders or ATLAS configuration.
- Save a disposable credential, restart, retrieve it through the UI, then remove it and verify removal. Verify that fallback session-only storage is disclosed. Do not include real secrets in screenshots or reports.
- Launch a second instance: the first window should activate and no second reader/outbox should run. Test crash/restart recovery. Check close-to-tray, restore and explicit Quit; confirm the user knows whether monitoring continues.
- Block SMTP and/or Telegram independently using normal lab policy. Check actionable channel-specific failures without GUI/reader hangs. Restore connectivity and ensure only the eligible active session can retry.

## Expendable ATLAS acquisition

- Confirm engine and execution full paths separately, including the `FIBIC` versus `Fibics` spelling. Validate only those explicit files, with no disk-wide search. Check each source independently and in Both mode.
- Start acquisition while monitoring, then stop/restart ATLAS normally. Confirm no new sharing/access errors are attributable to the watchdog. Its flags cannot override vendor exclusivity, and vendor exclusive reopen can conflict while a brief reader handle exists.
- Exercise normal job startup/shutdown, the vendor's real rename/rotation behavior, truncation/replacement if safely reproducible, and lengthy acquisition. Confirm acquisition output and vendor behavior match an unmonitored control run. Do not manufacture errors on valuable live acquisitions.
- Confirm growing source data is found even if Explorer still reports 0 KB or unchanged metadata. Confirm source health says Missing/Unreadable for unavailable logs while the other source still reads.
- With a known harmless representative appended record or dedicated simulator, verify ENGINE/EXECUTION badges, complete message/context, rule IDs, logged level versus assigned severity, and notification statuses. Do not append test records to real configured ATLAS files.
- Verify new-entries baseline, partial historical line handling, historical review without automatic sending, and valid checkpoint resume. Replacement coverage warnings must be understandable; unread old-generation tails are not guaranteed recovered.
- Arm execution activity with a generous threshold, then pause the simulator. Verify cycles/duration, startup grace, one incident, reminders and recovery. Keep engine activity unarmed until its normal cadence is understood. Heartbeat with unchanged progress must not imply successful imaging.
- Verify `Run Ended.` records an end and preserves prior faults. Select EHT/standby rules deliberately if desired; both EHT wording variants are separate literal presets.

## Delivery and session semantics

- Configure a dedicated real Gmail account and/or Telegram bot using the setup guides. Deliberately send a TEST per enabled channel and each intended recipient; verify received contents, spam folder and phone sound/popup/DND settings. No real recipients are contacted by the automated tests.
- While monitoring runs, turn alerts off: detection/history must continue, without external sends. Arm alerts for future events. Stop/rearm each control while work is pending and in flight; stale work must not send automatically.
- Restart with undelivered/uncertain entries. Confirm explicit resend/discard is required and Unknown acceptance is not described as guaranteed failure. Provider acceptance must not be described as human receipt.
- Check short bursts and distinct faults: each remains visible, repeats have count/context, numeric differences are retained, and channel rate limits are visible.
- Test sleep/resume, workstation lock versus logout, network outage and loss of local writable storage using dedicated test state. Confirm coverage/degraded reliability warnings and startup grace. The same PC cannot send an immediate power/OS-failure report.
- Export history/configuration to a safe separate folder, with raw context only by choice. Confirm no secrets and no possible overwrite of monitored files. Check retention/deletion deliberately with disposable state.

Retain your completed acceptance record outside source directories. If a sharing limitation, unsupported OS, unresolved storage problem or untested delivery path remains, treat that limitation explicitly in the laboratory response procedure.
