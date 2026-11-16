# Third-party notices and redistribution

## Version 0.1.7 legacy profile

The separate legacy artifact uses **CPython 3.10.11**, **PySide2/Shiboken2 5.15.2.1** and **Qt 5.15.2**. It contains QtCore/Gui/Widgets/Network, Qt5Qml (a direct native dependency of pyside2.abi3.dll), and a filtered set of widget/platform/image plugins, with no Qt 6, Python QML module/content, Quick, WebEngine or Virtual Keyboard. These Qt/PySide components retain the LGPLv3 option and replacement/source obligations described below. The complete diagnostic folder, application source/locks/build scripts, licence texts and exact dependency record accompany the one-file executable. Allow interface-compatible library replacement and reverse engineering for debugging such modifications.

Matching upstream source: [Qt 5.15.2 official submodule archives](https://download.qt.io/archive/qt/5.15/5.15.2/submodules/) including qtbase and required embedded components, [PySide/Shiboken v5.15.2.1 source](https://github.com/pyside/pyside-setup/tree/v5.15.2.1), and [CPython 3.10.11 source/licence](https://www.python.org/downloads/release/python-31011/). Wheel-supplied LGPL/GPL/third-party notices and Python's incorporated OpenSSL/SQLite/Microsoft-runtime notices are collected in `third_party_licenses/`. Preserve those notices and use the source-availability mechanism required for the particular redistribution; upstream links alone do not replace that obligation.

Legacy build-only changes: setuptools 80.9.0 (MIT), wheel 0.45.1 (MIT), pip 23.0.1 (MIT and vendored licences), tomli 2.5.0 (MIT) and exceptiongroup 1.3.1 (MIT). Other versions remain as listed below and fully recorded in `requirements-legacy-lock.txt` / `BUILD-DEPENDENCIES.json`. The legacy CPython/OpenSSL/public Qt wheel versions are no longer current security-maintained releases; see [legacy-build.md](docs/legacy-build.md).

Microsoft runtime files supplied with the PSF/Qt distributions retain Microsoft's terms; app-local packaging does not grant unrestricted redistribution. See [Microsoft redistribution documentation](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170) and the supplied runtime notices. No random/system-directory DLL collection is intended. The following Qt 6/Python 3.12 inventory continues to describe the **modern** profile.

ATLAS Watchdog uses **Qt/PySide6 6.8.3**, including QtCore, QtGui, QtWidgets and QtNetwork, through dynamic Qt libraries. Qt is copyright The Qt Company and its contributors; PySide/Shiboken are copyright The Qt Company and contributors. The selected open-source Qt/PySide components are used under the LGPL version 3 option where applicable. Qt's other available commercial/GPL terms do not imply a commercial licence was purchased for this utility. The specs filter optional input/image plugins and their libraries, including the unused [GPL/commercial Virtual Keyboard](https://doc.qt.io/qt-6.8/qtvirtualkeyboard-index.html), PDF, SVG, and QML/Quick stacks; they retain the Windows platform and ordinary icon handlers required by this widget application.

Copies of the Qt LGPL/GPL and an intentionally inclusive set of Qtbase licence texts are in `docs/licenses/`. Upstream Qtbase attribution metadata is included there when collected. Wheel-supplied licence/notice files and Python's licence are collected into `third_party_licenses/` in packaged artifacts. Some wheel metadata includes only a commercial reference text; the explicit LGPL/GPL copies accompany it to document the open-source option. An inclusive licence collection does not mean every Qt module/component is imported or bundled.

| Dependency | Version | Licence / upstream source |
|---|---|---|
| CPython | 3.12.13 | PSF-2.0 and incorporated component notices; [Python licence](https://docs.python.org/3.12/license.html), [source](https://www.python.org/downloads/source/). |
| PySide6 / PySide6 Essentials / PySide6 Addons / Shiboken6 | 6.8.3 | LGPL-3.0/GPL/commercial alternatives in wheel metadata; use LGPL-compatible modules only. [Qt for Python licensing](https://doc.qt.io/qtforpython-6.8/commercial/index.html), [licences used](https://doc.qt.io/qtforpython-6.8/licenses.html), [source tag](https://code.qt.io/cgit/pyside/pyside-setup.git/tree/?h=v6.8.3). |
| Qt | 6.8.3 | LGPL-3.0/GPL/commercial options and third-party notices; [licensing](https://doc.qt.io/qt-6.8/licensing.html), [Qtbase source tag](https://github.com/qt/qtbase/tree/v6.8.3), [official source archives](https://download.qt.io/archive/qt/6.8/6.8.3/submodules/). |
| HTTPX | 0.28.1 | BSD-3-Clause; [official repository](https://github.com/encode/httpx). |
| httpcore | 1.0.9 | BSD-3-Clause; [official repository](https://github.com/encode/httpcore). |
| h11 | 0.16.0 | MIT; [official repository](https://github.com/python-hyper/h11). |
| AnyIO | 4.16.0 | MIT; [official repository](https://github.com/agronholm/anyio). |
| certifi | 2026.10.23 | MPL-2.0 (CA bundle); [official repository](https://github.com/certifi/python-certifi). |
| idna | 3.20 | BSD-3-Clause; [official repository](https://github.com/kjd/idna). |
| typing_extensions | 4.16.0 | PSF-2.0; [official repository](https://github.com/python/typing_extensions). |
| tzdata | 2025.2 | Apache-2.0 package, with public-domain IANA data; [official repository](https://github.com/python/tzdata). |

Development/build dependencies are pinned separately in `requirements-lock.txt`: pytest (MIT), pluggy (MIT), iniconfig (MIT), colorama (BSD), packaging (Apache-2.0 OR BSD-2-Clause), setuptools (MIT and vendored notices), altgraph (MIT), pefile (MIT), pywin32-ctypes (BSD), PyInstaller hooks (their included licence), and **PyInstaller 6.16.0** (GPL-2.0 with the bootloader distribution exception, plus selected Apache-2.0 files). See [PyInstaller's official licence explanation](https://pyinstaller.org/en/stable/license.html). The exception permits distributing bundled applications under a chosen application licence while retaining dependencies' obligations. These tools need not all be runtime imports; metadata licences are included conservatively.

Python's bundled OpenSSL, SQLite, compression libraries and any Qt-embedded third-party libraries retain their own notices. Preserve the licence collection and the exact build/source records when redistributing. Optional code signing does not replace licence obligations.

## Qt replacement and source availability

Qt's [official LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations) and [open-source FAQ](https://www.qt.io/faq/qt-open-source-licensing) describe library modification/relinking and reverse-engineering rights. Do not apply a restriction that prevents recipients from exercising those rights.

For a one-folder release, preserve the dynamic Qt DLL layout and permit replacement with interface-compatible modified Qt libraries. For a one-file release, also provide the complete application source, this lock/spec/build tooling and the matching Qt/PySide corresponding-source access needed to rebuild with modified libraries. The public release includes the MIT-licensed application source, build instructions, a diagnostic one-folder archive, licence notices, and links to the matching unmodified Qt/PySide sources; a one-file EXE alone is not a complete LGPL redistribution package. Requests about corresponding third-party source can be made through the public repository's GitHub Issues.

The matching upstream sources are Qt 6.8.3 (at least Qtbase and the actual bundled modules) and PySide/Shiboken 6.8.3. Official Qt archives are linked above; PySide source is tagged `v6.8.3`. Review actual PyInstaller analysis output to confirm the modules shipped. If modified, preserve patches and build instructions and supply the corresponding modified source. A downstream release must make the required source available using an applicable licence mechanism, rather than assuming an upstream link alone satisfies every distribution scenario.

To rebuild against a compatible modified dependency, create a separate CPython 3.12 x64 environment, install the modified Qt/PySide wheels instead of their lock entries, install the remaining compatible pinned packages, install this application source with `--no-deps`, run the tests, then run the provided PyInstaller specs. Document any necessary modified-wheel/toolchain build instructions and retain installation information. This project's source/build automation is supplied to make replacement practical; the clean-machine compatibility tests must be repeated for any such build.

The application's own code is released under the [MIT License](LICENSE); this notice records the separate dependency terms. External licence review was not performed.
