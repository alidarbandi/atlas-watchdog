# ATLAS Watchdog v0.1.7 — legacy Windows compatibility

This release adds a separate **Windows 10 1607 x64** build for the ATLAS microscope workstation, preserving the existing Qt Widgets interface and read-only monitoring behavior. The owner confirmed on November 23, 2026 that the previously delivered legacy executable fixed the Windows startup issue.

## Downloads

- **Legacy standalone:** `ATLASWatchdog-Win10-1607-x64.exe` — Windows 10 1607 x64.
- **Complete legacy folder:** `ATLASWatchdog-v0.1.7-legacy.zip` — extracts `legacy/`, with the portable executable, full diagnostic application, guides, source, notices and hashes.
- **Legacy diagnostic only:** `ATLASWatchdog-Win10-1607-x64-debug.zip` — extract and keep the folder together.
- **Modern standalone:** `ATLASWatchdog.exe` — Windows 10 1809+ / Windows 11 x64.
- **Modern diagnostic:** `ATLASWatchdog-debug.zip`.
- **Source and integrity:** `ATLASWatchdog-source.zip`, `SOURCE-COMMIT.txt`, `BUILD-RELEASE.json` and `SHA256SUMS.txt`.

The standalone executables include Python/Qt and need no separate installation or administrator access for ordinary operation. Monitoring and automatic external alerts start **off**. Confirm x64 architecture and start with disposable/demo sources as described in the acceptance guide.

## Changes and verification

- Separate pinned Python 3.10.11 / PySide2 5.15.2.1 legacy profile; the Python 3.12.13 / Qt 6.8.3 modern profile remains available.
- Qt-free startup preflight/diagnostics; profile-specific native libraries/plugins and notices; shared state/schema/credential references and cross-profile instance protection retained.
- Batched event-table updates fix a Qt 5 burst-related UI stall. The bounded 90-second source soak passed after the correction.
- The initial build-host verification passed **274 source tests per profile**, repeated packaged demos, copied-state upgrades, cross-profile locking/crash recovery and tray lifecycle. The release workflow reruns source tests and both packaged demo formats before publication.
- Source logs remain read-only; source protection, TLS, credential storage and alert eligibility are preserved. Automated tests use disposable fixtures and mocks, and send no real Gmail/Telegram messages.

Public binaries are rebuilt in Windows CI from the release source and pinned profiles. Their bytes/hashes can differ from the locally built executable the owner tested. CI on Windows Server 2022 does **not** independently establish compatibility with 14393.3884; exact-build inventory, full acquisition acceptance, clean-machine and real provider/phone delivery checks remain separate. See the repository verification report for the evidence and remaining gates.

The legacy runtime uses older Python/Qt/OpenSSL dependencies. Preserve the source, corresponding dependency notices and replacement/build instructions when redistributing. Existing v0.1.6 release assets remain available unchanged.
