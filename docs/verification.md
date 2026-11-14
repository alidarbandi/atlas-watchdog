# Verification record

Development host: Windows 11 x64, build 26100. Runtime: CPython 3.12.13. Dependency set: `requirements-lock.txt`.

Reader/parser/adversarial-review verification completed on the actual Windows host: 45 tests passed, including exact read-only shared flags, a concurrent shared writer, the explicit exclusive-reopen limitation, stale zero-byte directory metadata, split encodings/BOMs/newlines, checkpoint corruption/replay, startup partial-line suppression, huge-record resynchronization, bounded record work, same-size replacement and same-file boundary rewrite. Full read-only sample parsing reproduced the supplied record counts; originals were not modified.

A built executable alone does not certify a clean Windows VM or microscope acquisition.

## Final integration results

Verified on November 13, 2026 on the development host:

| Check | Actual result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **253 passed** after the v0.1.6 public-release and disabled-channel guidance update. |
| Native GUI tests | 11 passed, including the non-sending SMTP-check settings gate, current-session filtering, real worker/source attribution, independent controls, responsive mocked transport, safe lock paths, and validation before Start/TEST. Included in the full-suite total. |
| Windows shared-file and Credential Manager integration | Passed on this host using disposable files and fake credentials. |
| `python -m PyInstaller packaging\onedir.spec --noconfirm` | Produced `dist\ATLASWatchdog-debug\ATLASWatchdog-debug.exe` and its dependencies. |
| `python -m PyInstaller packaging\onefile.spec --noconfirm` | Produced the windowed portable `dist\ATLASWatchdog.exe`. UPX disabled. |
| Packaged one-folder `--demo --smoke-test` | Exit 0; both source checkpoints advanced; execution fault events stored; native screenshot inspected. |
| Packaged one-file `--demo --smoke-test` | Exit 0; both source checkpoints advanced; execution fault events stored; native screenshot inspected. |
| Python dependency lookup during packaged smoke | Both launched with PATH restricted to Windows/System32, with no Python on PATH. This is **not** a clean-machine test; Python remains installed on the host. |
| `powershell -NoProfile -File scripts\check-windows.ps1` | Exit 0; detected Windows 11 Pro x64, build 26100. |

Automated tests sent no real Gmail/Telegram messages. Provider tests used mocks; secure-store tests used disposable fake secrets and removed them. Separately, the user reported receiving a real Gmail TEST from v0.1.5 on this PC. That verifies their configured account and recipient at that time, not other networks or accounts. The historical supplied logs were read only; sanitized representative fixtures are distributed instead.

Version 0.1.1 distinguishes missing folders (Windows code 3), missing files, access denial, sharing/lock conflicts, and network paths. Watchdog health events no longer appear as malformed ATLAS source lines. Its update artifacts are under `dist/v0.1.1/` so an existing running executable need not be overwritten.

Version 0.1.2 recognizes the exact observed engine header `Application log` and blank separators without generating parse-health warnings. Raw text and any real decode diagnostics remain visible. Context resets on monitoring-session changes and file-generation changes. Update artifacts are under `dist/v0.1.2/`; prior false warnings stay in stored history until acknowledged or deliberately deleted.

Version 0.1.3 fixes historical replay after editor saves in an ongoing new-entry session. Regression tests include a roughly 3 MB Windows-1252 log rewritten as UTF-8 with a fresh EHT entry: only the new EHT record becomes a matched event, and no old Error records are replayed. Atomic replacement, UTF-16 conversion, bounded catch-up, truncation, repeated/distant anchors, and conservative EOF fallback are covered. Events & history defaults to Current session only; older history remains available by deliberate selection. Versioned artifacts are under `dist/v0.1.3/`.

Version 0.1.4 addresses additional editor-save cases: inserting a record before trailing blanks, normalizing line endings, completing a live partial record during replacement, and completing a historical partial line without alerting on it. Empty-file and first-partial recovery are covered as well. Whole historical records are not replayed; genuinely ambiguous history changes continue to produce a coverage warning. Versioned artifacts are under `dist/v0.1.4/`.

The one-file v0.1.4 app was also exercised interactively using isolated state and a private copy of the supplied execution file's ending. Starting at EOF produced no historical matches. A rewritten save inserted a fresh EHT record before trailing blanks; a second save atomically replaced the file while completing an observed partial EHT record. Both new records were captured once and no historical faults were replayed. Successful reconciliation is recorded as an informational source-change event rather than an alarming coverage warning. No real notification channels were enabled during these checks.

Version 0.1.5 distinguishes SMTP protocol/capability errors from network errors (SMTPException inherits OSError), identifies the failing SMTP phase and endpoint, and adds a credential-free TLS/SMTP connection check. Unit tests ensure this check never authenticates or sends a message and never records a provider acceptance. Explicit TEST requests preserve retry/unknown classifications without automatic resending. Independent no-authentication probes on this PC verified DNS and TLS/SMTP handshakes on both 465 and 587; these probes do not establish account/password validity or real delivery. Versioned artifacts are under `dist/v0.1.5/`.

The installed one-file v0.1.5 executable was also checked through its new GUI action against the saved port 465 setting. It returned `connection_ok` after verified TLS and SMTP capability negotiation, with `authenticated=false` and `email_sent=false`. Monitoring and external alerts remained off. This verifies current connectivity from the actual executable, not the saved password or email delivery.

Version 0.1.6 adds a clear explanation when Start alerts is clicked with no delivery channel enabled, plus public setup steps and an MIT licence. It excludes development screenshots that revealed local Windows user and computer names from the public source and packaged documentation. This change does not require the user to stop their running v0.1.5 monitoring session.

Both v0.1.6 packaged formats passed isolated `--demo --smoke-test` runs (exit 0). The diagnostic folder and one-file archive were checked for the excluded screenshots. Release archives were checked for private screenshot names, local state and raw sample-log names; all release-asset hashes were verified against `SHA256SUMS.txt`.

The portable executable, diagnostic folder, source archive and SHA256 manifest are under the versioned `dist/v0.1.6/` release folder. Build logs and packaged-smoke state/screenshots are under `build/`; these are development artifacts, not source logs. The CI workflow is supplied for Windows builds.

## Checks requiring the user's environment

- Clean supported Windows VM/PC without Python, including one-file extraction, Qt plugin discovery and user Credential Manager.
- Microscope workstation `winver`/architecture, vendor acquisition startup/shutdown/rotation and long-running read-sharing acceptance.
- Deliberate real Gmail/Telegram test and each recipient/phone's notification behavior under lab network policy.
- Institutional unsigned-binary/antivirus policy, display/DPI requirements, proxy/CA constraints and sleep/logout procedures.

The application is observational and best effort. No test proves zero interference, continuous coverage during sleep/power failure, recovery of overwritten/unobserved rotated data, human notification receipt, or exactly-once external delivery under network uncertainty.
