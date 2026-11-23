# ATLAS Watchdog for legacy Windows

The **Windows 10 1607 x64** build preserves the ATLAS Watchdog interface with a separate Python 3.10 / Qt 5 runtime. The owner reported on **November 23, 2026** that it fixed the Windows compatibility/startup issue on the ATLAS PC.

## Downloads

- **[Standalone legacy EXE](https://github.com/alidarbandi/atlas-watchdog/releases/download/v0.1.7/ATLASWatchdog-Win10-1607-x64.exe)** — save to a normal folder and run. Python, Qt and administrator access are not required for ordinary operation.
- **[Complete legacy folder ZIP](https://github.com/alidarbandi/atlas-watchdog/releases/download/v0.1.7/ATLASWatchdog-v0.1.7-legacy.zip)** — extracts a `legacy/` folder with the portable executable, full diagnostic application/dependencies, guides, source, pinned dependencies and checksums. Keep the diagnostic application's dependency folder intact.
- [Diagnostic application ZIP only](https://github.com/alidarbandi/atlas-watchdog/releases/download/v0.1.7/ATLASWatchdog-Win10-1607-x64-debug.zip).
- [Release SHA256 checksums](https://github.com/alidarbandi/atlas-watchdog/releases/download/v0.1.7/SHA256SUMS.txt) and [application source](https://github.com/alidarbandi/atlas-watchdog/releases/download/v0.1.7/ATLASWatchdog-source.zip).

Executable downloads are published as GitHub release assets. This repository folder contains their permanent links and instructions; generated binaries are kept out of Git history.

## First launch

Confirm the destination is **x64 Windows** using the read-only [check-windows.ps1](../scripts/check-windows.ps1) with `-Profile legacy`. Monitoring and automatic external alerts both start off. Begin with disposable/demo sources using the [acceptance guide](../docs/legacy-acceptance.md); select real logs and enable monitoring deliberately. The application only observes ATLAS logs and never controls the microscope.

Modern and legacy profiles share `%LOCALAPPDATA%\ATLASWatchdog` configuration/history and the same single-instance protection. Do not place application output in ATLAS/source directories. Owner-reported startup success does not establish long acquisition behavior or real Gmail/Telegram receipt.

## Build and support records

Use [requirements-legacy-lock.txt](../requirements-legacy-lock.txt), [legacy build instructions](../docs/legacy-build.md) and `scripts\build.ps1 -Profile legacy`. The build outputs `dist/v0.1.7/legacy/`. The [verification report](../docs/legacy-verification.md) distinguishes owner feedback, source tests, packaged smoke tests and remaining checks.

The legacy profile uses older Python/Qt/OpenSSL dependencies to run on the fixed workstation OS. See the [compatibility report](../docs/legacy-build.md) and [third-party notices](../THIRD_PARTY_NOTICES.md) for dependency support and redistribution details. The modern profile remains available separately.
