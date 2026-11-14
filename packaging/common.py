"""Shared PyInstaller data selection. Never bundles source logs or credentials."""
from importlib.metadata import distributions
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files


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


EXCLUDES = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
            "PySide6.QtQuick", "tkinter", "numpy", "matplotlib", "IPython"]


def widget_binaries(entries):
    """Qt's broad image/input hooks pull unused modules; ship only this app's needs.

    In particular, the optional virtual-keyboard plugin can drag GPL-only
    QtVirtualKeyboard and a full QML stack into an otherwise LGPL widget app.
    PNG support is in QtGui; these optional handlers cover normal desktop icons.
    """
    qt_libraries = {"qt6core.dll", "qt6gui.dll", "qt6widgets.dll", "qt6network.dll"}
    plugins = {"platforms/qwindows.dll", "platforms/qoffscreen.dll", "platforms/qminimal.dll",
               "styles/qmodernwindowsstyle.dll", "imageformats/qico.dll", "imageformats/qjpeg.dll",
               "imageformats/qgif.dll", "networkinformation/qnetworklistmanager.dll",
               "tls/qcertonlybackend.dll", "tls/qopensslbackend.dll", "tls/qschannelbackend.dll"}
    result = []
    for entry in entries:
        target = entry[0].replace("\\", "/").lower()
        name = target.rsplit("/", 1)[-1]
        if name.startswith("qt6") and name.endswith(".dll") and name not in qt_libraries:
            continue
        if target.startswith("pyside6/plugins/") and target.split("/plugins/", 1)[1] not in plugins:
            continue
        result.append(entry)
    return result
