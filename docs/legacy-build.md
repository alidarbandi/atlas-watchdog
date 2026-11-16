# Reproduce the Windows 1607 candidate

Version 0.1.7 has two isolated Windows x64 profiles. The legacy candidate is **UNVERIFIED ON THE TARGET OS** (Windows 10 Enterprise 2016 LTSB 1607, 14393.3884). Artifact naming and a passing preflight do not certify compatibility. See [verification](legacy-verification.md) and [acceptance](legacy-acceptance.md).

## Build environments

Legacy uses the official PSF **CPython 3.10.11 Windows x64 installer** (`python-3.10.11-amd64.exe`, PSF Authenticode signature verified on the build host). This is the last 3.10 release with official Windows installers. Install on the development machine only, per-user; no Python installation is needed on the destination. Modern uses **CPython 3.12.13 x64**, obtained on this host with `uv python install 3.12.13` (Astral python-build-standalone). Do not substitute a different patch silently. The build script validates exact patches, lock versions and absence of another Qt binding.

The downloaded PSF installer SHA256 was `d8dede5005564b408ba50317108b765ed9c3c510342a598f9fd42681cbe0648b`. Its unchanged `LICENSE.txt` includes Microsoft's runtime redistribution conditions and incorporated OpenSSL notices. The legacy bundle's VCRUNTIME140/140_1 at its Python root are **14.29.30139.0**; Qt/Shiboken runtime copies and MSVCP140/MSVCP140_1/CONCRT140 are **14.24.28127.4**. `NATIVE-IMPORTS.json` records hashes and matching supplying distributions. The native Qt libraries are Core, Gui, Widgets, Network and the binding-required Qml library, all **5.15.2**.

From the source root in PowerShell 5.1 or newer, using the full path to the intended base interpreter:

```powershell
& 'C:\path\to\Python310\python.exe' -m venv .venv-legacy
.venv-legacy\Scripts\python.exe -m pip install -r requirements-legacy-lock.txt
.venv-legacy\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
$env:ATLAS_WATCHDOG_PROFILE = 'legacy'
.venv-legacy\Scripts\python.exe -m atlas_watchdog --preflight
.venv-legacy\Scripts\python.exe -m pytest -q
.\scripts\build.ps1 -Profile legacy
```

For modern, create `.venv` with CPython 3.12.13, install `requirements-lock.txt`, install the project with the same flags, and use `ATLAS_WATCHDOG_PROFILE=modern` and `build.ps1 -Profile modern`. Separate environments prevent accidental inclusion of two Qt bindings. Source runs select the profile explicitly; frozen artifacts have a fixed profile embedded by a runtime hook and ignore environment overrides.

The build script tests first, builds one-folder and one-file forms, and prepares release documents, source, dependency metadata and SHA256 sums. `-Format OneFolder` / `OneFile` and `-SkipTests` support rebuilding an already tested tree. Outputs are `dist/v0.1.7/legacy/` and `dist/v0.1.7/modern/`; neither overwrites historical releases. Builds must run on Windows. CI uses Windows Server 2022 and cannot certify 1607.

## Dependency choice

| Component | Legacy selection and evidence |
|---|---|
| CPython | 3.10.11 x64. [Release files](https://www.python.org/downloads/release/python-31011/) and [Windows baseline](https://docs.python.org/3.10/using/windows.html) (8.1+). The application deliberately restricts legacy to Windows 10 build 14393+. |
| Qt/PySide/Shiboken | PySide2 and Shiboken2 **5.15.2.1**, Qt **5.15.2**. Actual wheel METADATA requires Python <3.11 and exactly matching Shiboken2. The `cp35.cp36.cp37.cp38.cp39.cp310-none-win_amd64` wheel is available in [PyPI metadata](https://pypi.org/pypi/PySide2/5.15.2.1/json). Qt 5.15's [official platform source](https://github.com/qt/qtdoc/tree/v5.15.2/doc/src/platforms) lists Windows 10 x86/x86_64 without a 1809 boundary. This supports a candidate, not proof on build 14393.3884. |
| PyInstaller | 6.16.0, prebuilt Windows x64 wheel/bootloaders; Python >=3.8,<3.15. Its [versioned requirements](https://pyinstaller.org/en/v6.16.0/requirements.html) list Windows 8+. Hooks **2026.10** support both selected bindings. No bootloader was locally compiled. |
| Build tools | setuptools **80.9.0** and wheel **0.45.1** support Python 3.10. Modern retains setuptools **84.2.1**. Legacy's full lock includes pip, pytest's tomli and AnyIO's exceptiongroup backport. |
| Network | HTTPX **0.28.1**, httpcore **1.0.9**, h11 **0.16.0**, AnyIO **4.16.0**, certifi **2026.10.23**, idna **3.20**, typing_extensions **4.16.0**. All installed requirements/markers and wheel tags are recorded in `BUILD-DEPENDENCIES.json`. HTTPX retains verified TLS and timeouts. Gmail uses Python ssl's verified default context and Windows root store; Telegram/HTTPX uses certifi. |
| Python native libraries | This legacy interpreter reports SQLite **3.40.1** and OpenSSL **1.1.1t**. `_sqlite3`, `_ssl`, OpenSSL DLLs and CA data are collected by PyInstaller. No new SQLite APIs or database schema are required. |
| Timezones | tzdata **2025.2**, included as package data for `zoneinfo`; source timezone parsing is regression tested. |

CPython 3.10 is [end of life as of October 2026](https://devguide.python.org/versions/); the 3.10.11 binary, OpenSSL 1.1.1t and public Qt 5.15.2 wheels are old and do not incorporate later security fixes. This legacy profile trades maintained dependencies for a candidate on the fixed workstation OS. Keep the maintained modern profile available. No TLS validation, credential protection or source safety checks were relaxed. Further updating this runtime would require building compatible patched dependencies and repeating the target gate.

## Packaging and Microsoft runtime

`packaging/common.py` retains QtCore/Gui/Widgets/Network plus Windows/offscreen/minimal platforms, standard styles and common image handlers. **The legacy wheel's `pyside2.abi3.dll` directly imports `Qt5Qml.dll`, so that one native library is also required and retained.** Its Python QML module, QML plugins/content, Quick, WebEngine, Virtual Keyboard and QtTest are excluded. Qt 5 has no Qt 6 TLS/network-information plugin layout. The opposing binding is excluded and binary contamination is checked. ANGLE/software-rendering dependencies are collected by the Qt hook when present. CONCRT140 from the same Qt wheel is explicitly collected for MSVCP140's delay import.

The original PSF interpreter and Qt wheels carry Microsoft runtime binaries; PyInstaller resolves their native imports. Do not copy DLLs from an arbitrary Windows installation. `scripts/inspect_bundle.py` records actual PE machines, imports and bundled runtime versions/provenance for review. Windows 10 supplies its OS/UCRT and API sets. App-local VC runtime deployment is described by [Microsoft](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170); redistribution rights remain subject to the supplying distributions' and Microsoft's terms. Preserve Python's bundled runtime notice and wheel notices. No separate redist installer or system DLL replacement is performed. Clean target resolution remains an acceptance gate.

## Startup and retained state

Preflight runs before any Qt import and distinguishes build 14393 (legacy) from 17763 (modern). It rejects x86 and ARM64. It records process/OS architecture, build/revision, Python and profile. Failure uses a native message/console with a nonzero exit. `startup.json` goes under `%LOCALAPPDATA%/ATLASWatchdog` only after source-output validation; only the latest attempt is retained. It excludes exception messages/locals, credentials, machine identifiers and scientific data. Python cannot catch bootloader/OS loader failures before Python starts.

The small `atlas_watchdog.qt` layer handles QAction, event-loop methods and Qt 5 DPI setup. Existing scoped enums work on both tested bindings. Config schema, credential prefixes, database schema, source checkpoints, state directory, lock file and local-server naming remain the same. Modern and legacy must not use one state directory simultaneously. Never test an upgrade against the user's live state.

The port does not change reader flags, parsing, alert eligibility, timers, rule matching or providers. Monitoring and automatic external alerts still start off. Demo explicitly starts simulated monitoring, with automatic alerts off. A smoke test now fails unless its worker, source views and execution events are present. Use the full acceptance guide for tray, display and actual acquisition behavior.

A bounded Qt 5 soak found repeated event-table column resizing could stall GUI updates during bursts. Cell updates now defer painting and column geometry until the batch ends, preserving column modes and selection. The same change is regression checked on the modern profile. Version-specific Qtbase/Qtdeclarative notices and attribution records are in `docs/licenses/qt5-5.15.2/`, with original URLs and hashes; they supplement the existing inclusive Qt 6 licence collection.
