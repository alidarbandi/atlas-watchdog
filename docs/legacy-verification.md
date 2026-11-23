# Version 0.1.7 verification

The original verification record in `verification.md` describes earlier releases. New results for this rebuild are recorded here; they do not certify the instrument PC.

Starting repository: `https://github.com/alidarbandi/atlas-watchdog`, commit `c64255213ba793e97412256dfcfd79ab0f51f510`. Local branch: `fix/windows-1607-compatibility`. Work began November 16, 2026 (America/Toronto); that initial delivery remained local. On November 23, the owner requested publication of the source and legacy downloads.

## Owner confirmation — November 23, 2026

The owner reported: **"This fixed the issue on legacy windows."** This confirms owner-reported startup/compatibility success for the previously delivered legacy executable on the ATLAS PC. The owner did not supply a new OS/build/runtime inventory, a detailed acquisition acceptance record or provider/phone delivery results. Preserve this distinction from independent exact-build certification.

The originally delivered standalone legacy executable's SHA256 is `aac6b8220ff52e56128669cabcebfadef62b252ccd2bbd6bf1c69fa4d4fa1782`, built from application source at `c8961d81c1cca76727b61bdaa0a6f84dcf74d09b`. Public release binaries are rebuilt with the same application source and pinned profiles by the Windows workflow; their hashes are published in the release's `SHA256SUMS.txt`. A passing CI build on Windows Server 2022 does not independently repeat the owner's workstation test.

**Target-OS validation PENDING: Windows 10 Enterprise 2016 LTSB 1607 build 14393.3884 has not been available.** No clean VM, Server 2016 substitute or instrument-PC test was performed. See `legacy-acceptance.md` for the concrete procedure.

## Actual environment and results

Build/test host: **Windows 10 Home 22H2 x64, 19045.6456**, ordinary non-administrator Windows account, PowerShell **5.1.19041.6456**. This differs from the target edition/build/revision. Legacy: official PSF CPython **3.10.11 x64**, Qt/PySide/Shiboken **5.15.2 / 5.15.2.1 / 5.15.2.1**. Modern: CPython **3.12.13 x64** (Astral standalone), Qt/PySide/Shiboken **6.8.3**. Full locks and installed METADATA/WHEEL records accompany each build.

| Check | Actual evidence on this host |
|---|---|
| Original checkout baseline | `python -m pytest -q`: **253 passed in 31.02 s**, modern environment, before edits. |
| Legacy full source suite | **274 passed**, including all original tests and 21 profile/preflight/packaging regressions. No skips. |
| Modern full source suite | **274 passed**, same test suite, no skips. |
| Windows-specific tests | Shared CreateFile flags, concurrent disposable writer, exclusive-reopen limitation and disposable fake Credential Manager roundtrip passed in both profiles; included in totals. |
| Build validation | Both exact Python patch versions, x64 architecture and locked dependencies validated; opposing bindings absent. |
| Windows executables | Both profiles built on this Windows host, diagnostic one-folder and windowed one-file, PyInstaller **6.16.0**, hooks **2026.10**, UPX disabled. |
| Packaged demos | Both formats/profiles passed repeated `--demo --smoke-test` runs, exit **0**, with advancing engine/execution checkpoints, execution events, SQLite integrity `ok`, and no eligible external outbox sends. Native legacy screenshot reviewed. |
| Restricted lookup/extraction | Packaged tests used PATH containing only Windows/System32, isolated LOCALAPPDATA/TEMP, and spaces/non-ASCII in state/extraction paths. Frozen profile remained correct despite an opposing environment override. This host still has Python installed: **not a clean-machine test**. |
| Existing state upgrade | Created state using untouched v0.1.6 source, copied it, opened the copy with legacy and then modern. Exact event/cursor data, configuration and fake credential reference retained; both launch controls off. Original fixture state preserved. |
| Cross-profile instances | Real one-folder executables tested both directions on shared disposable state. Second process exited in **0.281 / 0.328 s** while owner remained running; after deliberate owner crash, opposite profile recovered and passed demo smoke (exit 0). |
| Bounded legacy source GUI soak | **90.015 s**, 128 events, burst/pause/resume/rotate/truncate and silence/recovery timers. Maximum observed event-pump gap **0.063 s**; 2 Python threads; handles 362 then 352; working set about **81.7–86.4 MiB** as history grew. Clean worker shutdown. This duration is not evidence of indefinite stability. |
| Native inspection | Legacy diagnostic folder: **57 x64 PE files**; exact imports, runtime versions/hashes/provenance recorded in `NATIVE-IMPORTS.json`. Qt 6, Quick, WebEngine, Virtual Keyboard and Python QML modules excluded; native Qt5Qml retained because PySide2 requires it. |
| Native tray lifecycle | Both source profiles on this host: system tray available, close hid the window while worker stayed running, restore showed it, tray Quit stopped the worker. Startup monitoring/alerts were both off. Target tray/display behavior remains pending. |
| PowerShell | All three scripts parsed successfully with the actual PowerShell 5.1 parser. File execution was blocked by this host's execution policy, so builds and packaged checks used the equivalent documented Python commands. No policy change was made. Script execution on the target remains pending. |

Local execution records and private screenshots/state are under `.evidence/` (excluded from Git/distribution). Only aggregate results and relative native metadata are distributed. Runs occurred November 16, 2026, starting around **14:13 America/Toronto**; detailed commands and UTC timestamps are retained locally. Dependency source links were consulted on that date.

The final source-suite runs completed with **274 passed in 9.85 s (legacy)** and **274 passed in 9.77 s (modern)**. Delivered artifact hashes, UTC report time, per-format repeated smoke counts/checkpoint offsets, tray/soak results and source commit are recorded in `VERIFICATION-RESULTS.json` alongside the binaries.

## Failures found and resolved

The first Qt 5 source run had **243 passed, 3 failed, 7 setup errors** because Qt 5's QTest lacks `qWait`. The existing event-pumping test helper now uses a short ordinary sleep between event pumps; assertions were retained.

Initial legacy packaging omitted **Qt5Qml.dll**. PE inspection established the actual direct import from **pyside2.abi3.dll**; retaining the required native library fixed the build-host ImportError. **This does not identify the missing export in the original Qt 6 failure on 14393.3884.** MSVCP140's CONCRT140 delay dependency is now bundled from its matching wheel as well.

The first complete soak failed a responsiveness assertion at **9.578 s** maximum event-pump gap; an instrumented repeat measured **9.5 s**. Profiling attributed **42.79 s** of the 91.989 s run to Qt 5 table `setItem` calls. Batched column/painting updates resolved it; the same assertion passed with a **0.063 s** maximum gap. It was not relaxed. Early verification-harness errors (case-sensitive environment dictionary lookup and incorrect tab attribute) were corrected before the successful runs. An upstream attribution file's literal tab required non-strict JSON reading; notices remain byte-for-byte unchanged.

## Reproduce checks

Use each profile's interpreter and `ATLAS_WATCHDOG_PROFILE` as described in `legacy-build.md`:

```powershell
.venv-legacy\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest -q
# Select the matching profile before each PyInstaller invocation:
.venv-legacy\Scripts\python.exe -m PyInstaller packaging\onedir.spec --noconfirm --clean --distpath dist\v0.1.7\legacy --workpath build\legacy\onedir
.venv-legacy\Scripts\python.exe -m PyInstaller packaging\onefile.spec --noconfirm --clean --distpath dist\v0.1.7\legacy --workpath build\legacy\onefile
.venv\Scripts\python.exe scripts\verify_packaged.py dist\v0.1.7\legacy\ATLASWatchdog-Win10-1607-x64.exe build\new-packaged-test
.venv-legacy\Scripts\python.exe scripts\soak_demo.py build\new-soak --seconds 90
.venv-legacy\Scripts\python.exe scripts\inspect_bundle.py dist\v0.1.7\legacy\ATLASWatchdog-Win10-1607-x64-debug --output dist\v0.1.7\legacy\NATIVE-IMPORTS.json
.venv-legacy\Scripts\python.exe scripts\prepare_release.py --profile legacy --output dist\v0.1.7\legacy
```

`verify_packaged.py` checks each artifact twice, including restart. `verify_instance_profiles.py` takes both one-folder executable paths and a new output directory. `verify_state_upgrade.py` takes a new output path, `--baseline-source` (the untouched original checkout) and `--legacy-python` (legacy interpreter path). These helpers use only disposable fixtures/fake credential references and no live provider requests.

## Separate deployment gates

1. **Source tests: PASSED**, both profiles on the identified build host.
2. **Windows executables: BUILT**, both formats/profiles.
3. **Packaged build-host smoke: PASSED**, both formats/profiles, repeated launch.
4. **Clean machine without Python/Qt: PENDING**, no disposable clean machine available.
5. **Legacy workstation startup: OWNER-REPORTED SUCCESS (November 23)**. Independent exact-target/substitute OS certification remains **PENDING**; no licensed 1607 VM/test PC was available to the agent. Build 19045 and CI's Server 2022 are not equivalent. Record the actual destination revision and installed runtimes when completing acceptance.
6. **Real microscope acquisition acceptance: PENDING**, instrument PC/logs not accessed.
7. **Real provider/phone delivery: PENDING for this rebuild**, no Gmail/Telegram messages sent. Existing historical reports do not certify this build. Owner must deliberately run each TEST and confirm receipt.

Tray interaction, all display scales, lab network/CA behavior, clean temporary extraction, exact-target loader resolution and long-duration acquisition still require the acceptance procedure. Do not describe this candidate as fully tested or target certified.
