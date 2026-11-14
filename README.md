# ATLAS Watchdog

A portable Windows desktop monitor for ZEISS/FIBICS ATLAS engine and execution logs. It detects configured faults and possible stalled activity, keeps local history, and can send Gmail and Telegram alerts. It never controls the microscope.

## Download and run on a new PC

Download **[ATLASWatchdog.exe](https://github.com/alidarbandi/atlas-watchdog/releases/latest/download/ATLASWatchdog.exe)** from the [latest release](https://github.com/alidarbandi/atlas-watchdog/releases/latest). Save it in a normal folder and double-click it. This is a single portable Windows x64 program; users do not need to install Python, Qt, Git, or a separate runtime. It has no installer and does not need administrator access for ordinary use. Windows 10 version 1809 or newer and Windows 11 x64 are the supported targets. The executable is unsigned, so follow your organization's normal software approval process.

On first launch, select **General → Log sources** (Engine, Execution, or Both), then use **Sources** to choose the real log files. The suggested engine path is only a suggestion; use **Validate/Test Read** to confirm each exact path. In General, keep **New entries only** to start from the current end of each log. Review the enabled rules, then click **Start monitoring**. New matching lines appear in Events & history. Monitoring and external alerts are separate controls and both start off on every launch.

To receive Gmail alerts:

1. Enable 2-Step Verification on the Google account that will send the alerts. Create a [Google app password](https://support.google.com/accounts/answer/185833) once for ATLAS Watchdog.
2. Open **Delivery → Gmail**. Enter that account as **Gmail sender**, your destination address under **Recipient(s)**, and the app password in **App password**. Keep **Store in Windows Credential Manager** checked and click **Save / replace secret**. The app reuses the saved password on future launches on the same Windows account and PC.
3. Click **Send TEST email** and confirm receipt. A successful test proves delivery works; it does **not** enable automatic alerts.
4. Check **Enable this external notification channel**, then click **Apply settings and rules**. Finally click **Start alerts** at the top. Future matching log entries can now send email. Earlier events are not sent automatically.

Telegram is optional; see the [Telegram guide](docs/telegram.md). For full source, rule, timing, and workstation guidance, use the [quick start](docs/quickstart.md), [Gmail setup](docs/gmail.md), and [workstation acceptance checks](docs/acceptance.md). The monitor must keep running to observe new log lines; it is not a Windows service.

## Run the application

The release executable requires no Python installation:

```powershell
.\dist\ATLASWatchdog.exe
```

The diagnostic one-folder executable is in the optional `ATLASWatchdog-debug.zip` release asset; keep its extracted folder together. The portable release is the single windowed `ATLASWatchdog.exe` file. Durable state is under `%LOCALAPPDATA%\ATLASWatchdog`, independent of the executable's location. Do not place application output in an ATLAS or monitored-source directory.

For development, use x64 CPython 3.12. The pinned environment used here is Python 3.12.13, PySide6/Qt 6.8.3, HTTPX 0.28.1, pytest 8.3.5, and PyInstaller 6.16.0. [Compatibility](docs/compatibility.md) explains why this targets Windows 10 version 1809 or newer, x64, and what remains to verify on the microscope PC.

Run `scripts\check-windows.ps1` on the destination PC for a read-only OS preflight, or collect its version/build with `winver`. Respect the laboratory's script and unsigned-application policies.

Using the installed `uv` tool:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-lock.txt
uv pip install --python .venv\Scripts\python.exe --no-deps --no-build-isolation -e .
.venv\Scripts\python.exe -m atlas_watchdog
.venv\Scripts\python.exe -m atlas_watchdog --demo
```

Alternatively, with an installed x64 CPython 3.12 interpreter:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

`requirements-lock.txt` pins the complete tested development/build environment. The application is installed separately so the lock contains no machine-specific editable path. Development needs internet access to install packages; routine monitoring does not, unless a notification channel is enabled or explicitly tested.

## What it does

- Independent engine/execution paths, cursors, rule lists, activity timers, and source health.
- Read-only, brief Windows shared reads, byte checkpoints, partial-line handling, file identity and boundary checks.
- Literal phrases and structured level rules, optional ignore rules, multi-rule events, bounded live views and SQLite history.
- Separate monitoring and external-alert controls; both start off. Explicit test sends work while automatic alerts are off.
- Per-source cycles/duration silence detection, optional execution heartbeat/progress watches, grace, reminders, and lifecycle pause.
- Gmail app-password SMTP with verified TLS; Telegram bot messaging and explicit private-chat discovery.
- Windows Credential Manager secrets with disclosed session-only fallback, durable per-recipient outbox, independent channel workers, bounded retry and conservative uncertain-acceptance handling.
- A labeled demo, history/configuration export without secrets, source-attributed details, local acknowledgment, and tray lifecycle.

No hosted server, OpenAI API, paid SMS API, Telegram Premium, public webhook, inbound firewall port, telemetry, or remote microscope commands are required. Telegram phone sounds/popups depend on phone settings. Provider acceptance does not establish that a person received or read an alert.

## Test and build

```powershell
.venv\Scripts\python.exe -m pytest -q
.\scripts\build.ps1
```

The script tests first, builds the diagnostic one-folder form, then builds the windowed one-file form. It also gathers release documentation, an application source archive, and a SHA256 manifest in `dist\`. `-Format OneFolder` or `-Format OneFile` selects a format. `-SkipTests` is available for an unchanged, already-tested tree. UPX is disabled. Windows binaries must be built on Windows. A Windows CI workflow is supplied in `.github/workflows/windows.yml`.

Actual verification results are recorded in [verification.md](docs/verification.md). Packaging on this development PC is distinct from testing on a clean PC without Python, and from an expendable ATLAS acquisition.

## Documentation and source

| Topic | Location |
|---|---|
| First monitoring session and demo | [Quick start](docs/quickstart.md) |
| Gmail account and test setup | [Gmail](docs/gmail.md) |
| Bot and phone notification setup | [Telegram](docs/telegram.md) |
| Controls, session eligibility, timing, history | [Monitoring policy](docs/monitoring-policy.md) |
| Sample-derived format and encoding details | [Source format](docs/source-format.md) |
| File sharing, coverage, source protection | [Safety](docs/safety.md) |
| OS/build requirements and fallback approach | [Compatibility](docs/compatibility.md) |
| Workstation acceptance and remaining checks | [Acceptance](docs/acceptance.md) |
| Diagnosing path, storage, or delivery failures | [Troubleshooting](docs/troubleshooting.md) |
| Code boundaries and worker ownership | [Architecture](docs/architecture.md) |
| Dependency notices and redistribution | [Third-party notices](THIRD_PARTY_NOTICES.md) |

`src/atlas_watchdog/` contains application code; `tests/` contains automated tests and sanitized fixtures; `packaging/` contains PyInstaller specifications; `scripts/` contains build tooling. Supplied historical sample logs remain reference inputs only and are not bundled or configured as live sources. Application code is [MIT licensed](LICENSE); bundled dependencies retain their own terms in [third-party notices](THIRD_PARTY_NOTICES.md).
