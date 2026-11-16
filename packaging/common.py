"""Shared PyInstaller data selection. Never bundles source logs or credentials."""
from importlib.metadata import distributions
from pathlib import Path
import sys
import os

from PyInstaller.utils.hooks import collect_data_files

PROFILE = os.environ.get("ATLAS_WATCHDOG_PROFILE", "modern")
if PROFILE not in {"legacy", "modern"}:
    raise ValueError("Unknown build profile")
BINDING = "PySide2" if PROFILE == "legacy" else "PySide6"
ARTIFACT = "ATLASWatchdog-Win10-1607-x64" if PROFILE == "legacy" else "ATLASWatchdog"


def profile_hook(root):
    destination = Path(root) / "build" / PROFILE / "profile_hook.py"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("import sys\nsys._atlas_watchdog_profile = " + repr(PROFILE) + "\n", encoding="utf-8")
    return str(destination)


def profile_binaries():
    if PROFILE != "legacy":
        return []
    from importlib.util import find_spec
    wheel = Path(find_spec("PySide2").origin).parent
    # MSVCP140's delay-import of CONCRT140 is not collected by normal analysis.
    # Use the matching redistributable supplied in the Qt wheel, never System32.
    return [(str(wheel / "concrt140.dll"), ".")]


def bundle_data(root):
    root = Path(root)
    result = [(str(root / "README.md"), "."),
              (str(root / "LICENSE"), "."),
              (str(root / "THIRD_PARTY_NOTICES.md"), ".")]
    # Demo screenshots from development can reveal the builder's Windows user
    # and computer names. Bundle the written guides and licence texts only.
    for document in (root / "docs").rglob("*"):
        if document.is_file() and document.suffix.lower() in {".md", ".txt", ".json"}:
            result.append((str(document), str(document.parent.relative_to(root))))
    result.extend(collect_data_files("tzdata"))
    # Wheel licence metadata is not imported automatically by module analysis.
    for dist in distributions():
        name = dist.metadata.get("Name", "dependency")
        for item in dist.files or []:
            if any(token in item.name.casefold() for token in ("license", "licence", "copying", "notice")):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    result.append((str(source), "third_party_licenses/" + name + "/" + str(item.parent).replace("..", "_")))
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        result.append((str(python_license), "third_party_licenses/Python"))
    return result


EXCLUDES = [BINDING + suffix for suffix in (".QtWebEngineCore", ".QtWebEngineWidgets", ".QtQml", ".QtQuick", ".QtTest")]
EXCLUDES += (["PySide6", "shiboken6", "PyQt5", "PyQt6"] if PROFILE == "legacy" else ["PySide2", "shiboken2", "PyQt5", "PyQt6"])
EXCLUDES += ["tkinter", "numpy", "matplotlib", "IPython"]


def widget_binaries(entries, profile=PROFILE):
    """Qt's broad image/input hooks pull unused modules; ship only this app's needs.

    In particular, the optional virtual-keyboard plugin can drag GPL-only
    QtVirtualKeyboard and a full QML stack into an otherwise LGPL widget app.
    PNG support is in QtGui; these optional handlers cover normal desktop icons.
    """
    major = "5" if profile == "legacy" else "6"
    binding = "pyside2" if profile == "legacy" else "pyside6"
    qt_libraries = {"qt" + major + module + ".dll" for module in ("core", "gui", "widgets", "network")}
    if profile == "legacy":
        # pyside2.abi3.dll itself imports Qt5Qml.dll in the upstream wheel.
        # Keep that native dependency, without collecting Python QML/Quick or plugins.
        qt_libraries.add("qt5qml.dll")
    plugins = {"platforms/qwindows.dll", "platforms/qoffscreen.dll", "platforms/qminimal.dll",
               "styles/qmodernwindowsstyle.dll", "imageformats/qico.dll", "imageformats/qjpeg.dll",
               "imageformats/qgif.dll", "networkinformation/qnetworklistmanager.dll",
               "tls/qcertonlybackend.dll", "tls/qopensslbackend.dll", "tls/qschannelbackend.dll"}
    if profile == "legacy":
        plugins = {"platforms/qwindows.dll", "platforms/qoffscreen.dll", "platforms/qminimal.dll",
                   "styles/qwindowsvistastyle.dll", "imageformats/qico.dll", "imageformats/qjpeg.dll", "imageformats/qgif.dll"}
    result = []
    for entry in entries:
        target = entry[0].replace("\\", "/").lower()
        name = target.rsplit("/", 1)[-1]
        if name.startswith(("qt5", "qt6")) and name.endswith(".dll") and name not in qt_libraries:
            continue
        if target.startswith(binding + "/plugins/") and target.split("/plugins/", 1)[1] not in plugins:
            continue
        if target.startswith(("pyside6/", "shiboken6/")) and profile == "legacy":
            raise ValueError("Qt 6 contamination in legacy artifact")
        if target.startswith(("pyside2/", "shiboken2/")) and profile == "modern":
            raise ValueError("Qt 5 contamination in modern artifact")
        result.append(entry)
    return result
