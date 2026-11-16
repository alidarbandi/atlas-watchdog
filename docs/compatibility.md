# Windows compatibility and reproducible builds

**Version 0.1.7 update:** The following Qt 6 baseline still applies to the modern profile. A separate Qt 5 / CPython 3.10 legacy candidate for Windows 10 1607 x64 now exists; see [its compatibility/build report](legacy-build.md). It is **UNVERIFIED ON THE TARGET OS**, with exact-target acceptance pending. The historical statement below that no legacy binary exists describes v0.1.6.

The selected release target is **Windows 10 version 1809 (build 17763) or newer, x64**, including Windows 11 x64. This is a dependency support intersection, not a claim that every microscope workstation has passed application acceptance.

| Component | Chosen version | Upstream baseline relevant here |
|---|---|---|
| CPython | 3.12.13 x64 | Python 3.12 supports Windows 8.1+; [Python Windows documentation](https://docs.python.org/3.12/using/windows.html). |
| PySide6 / Qt | 6.8.3 | Qt 6.8 lists Windows 10 1809+ x86_64; [Qt supported platforms](https://doc.qt.io/qt-6.8/supported-platforms.html), [Windows details](https://doc.qt.io/qt-6.8/windows.html). This determines the stricter application baseline. |
| PyInstaller | 6.16.0 | Windows 8+ build host support; [versioned requirements](https://pyinstaller.org/en/v6.16.0/requirements.html). |
| HTTPX | 0.28.1 | HTTPS transport with explicit timeouts; dependencies are pinned in `requirements-lock.txt`. |
| tzdata | 2025.2 | Bundled timezone data for optional IANA source timezones on Windows. |

Development verification was performed on Windows 11 x64, OS build 26100, using CPython 3.12.13. See [verification.md](verification.md) for actual test/build results. No clean Windows 10 VM or microscope PC has been certified by that development run.

Before installing at the instrument:

1. Press Win+R, run `winver`, and record Windows edition, version and OS build. In Settings → System → About, record system type (x64 versus ARM64/32-bit).
2. Confirm the lab's policy for unsigned portable executables, outbound Gmail/Telegram, proxy/CA configuration and user-writable `%LOCALAPPDATA%`.
3. Use the diagnostic one-folder build first. Keep its DLLs/plugins together. Check that Qt starts, scaling is readable and Credential Manager access works for that user.
4. Run the packaged-app and expendable-acquisition checks in [acceptance.md](acceptance.md). Python need not be installed on the target PC; the release bundles it.

For Windows 10 **older than 1809**, Windows 8.1/7, 32-bit Windows or ARM64, this exact PySide6/Qt wheel set is not a supported build. Do not assume the newest wheels or copying DLLs will fix that. The feasible primary approach is an institution/vendor-approved upgrade or a separate supported Windows PC reading an explicitly authorized log share, with network-share behavior acceptance-tested. Do not change a microscope OS without vendor/IT authorization.

If the workstation cannot change and monitoring must run there, create a separately maintained legacy build: verify an older Qt/Python/packager combination against that exact OS and architecture, obtain compatible wheels/source/toolchains, resolve security-support constraints, and rerun the full file-sharing and acquisition acceptance suite. A Qt5/PySide2 port is a source/API/dependency project rather than a supported switch for this release. No legacy binary is claimed here.

Windows binaries must be built on Windows with the same intended architecture. PyInstaller is not a cross compiler; [operating modes/platform builds](https://pyinstaller.org/en/stable/operating-mode.html). One-file builds unpack dependencies into a temporary directory, so durable state must remain in per-user local application data. Keep the source/lock/specs with a release to reproduce and replace dependencies. Dependency pins record the tested set; they are not a promise of indefinite maintenance or network-provider compatibility.

Optional code signing can help institutional distribution but is not required to develop or privately test the utility. Do not disable antivirus or bypass organizational execution controls. A flagged build should be reviewed through the lab's normal IT process.
