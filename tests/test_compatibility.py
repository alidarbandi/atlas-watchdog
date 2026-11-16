"""Regression checks shared by both isolated profile environments."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from atlas_watchdog import runtime


@pytest.mark.parametrize("profile,build,passes", [
    ("legacy", 14392, False), ("legacy", 14393, True),
    ("legacy", 17763, True), ("modern", 14393, False),
    ("modern", 17762, False), ("modern", 17763, True), ("modern", 19045, True),
])
def test_actual_profile_boundaries(profile, build, passes):
    assert (not runtime.baseline_errors(profile, "win32", 10, 0, build, "x64", "x64")) == passes


@pytest.mark.parametrize("process,system", [("x86", "x64"), ("x64", "arm64"), ("arm64", "arm64"), ("x64", "x86")])
def test_x64_artifact_rejects_other_architectures(process, system):
    assert runtime.baseline_errors("legacy", "win32", 10, 0, 14393, process, system)


def test_windows_81_is_below_legacy_boundary():
    assert runtime.baseline_errors("legacy", "win32", 6, 3, 9600, "x64", "x64")


def test_frozen_profile_cannot_be_overridden(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_atlas_watchdog_profile", "legacy", raising=False)
    monkeypatch.setenv("ATLAS_WATCHDOG_PROFILE", "modern")
    assert runtime.selected_profile() == "legacy"


def test_invalid_source_profile_fails(monkeypatch):
    monkeypatch.setenv("ATLAS_WATCHDOG_PROFILE", "typo")
    with pytest.raises(ValueError, match="must be"):
        runtime.selected_profile()


def test_preflight_loads_no_qt_or_controller():
    code = "from atlas_watchdog.runtime import preflight; import sys,json; print(json.dumps(preflight())); assert not any(n.startswith(('PySide','shiboken')) for n in sys.modules); assert 'atlas_watchdog.controller' not in sys.modules"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["profile"] == runtime.selected_profile()


def test_startup_report_redacts_messages_and_locals(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    try:
        raise ImportError("secret fake-token scientific-message")
    except ImportError as exc:
        destination = runtime.write_startup_report(runtime.preflight(), exc)
    content = destination.read_text(encoding="utf-8")
    assert "secret" not in content and "fake-token" not in content and "scientific-message" not in content
    report = json.loads(content)
    assert report["status"] == "failed" and report["exception"] == "ImportError"
    assert report["frames"][-1]["function"] == "test_startup_report_redacts_messages_and_locals"


def test_preflight_refuses_diagnostic_write_into_configured_sources(tmp_path, monkeypatch):
    from atlas_watchdog.config import defaults
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    directory = tmp_path / "ATLASWatchdog"
    directory.mkdir()
    config = defaults()
    config["sources"]["engine"]["folder"] = str(directory)
    (directory / "config.json").write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="outside source"):
        runtime.write_startup_report(runtime.preflight())
    assert not (directory / "startup.json").exists()


def test_qt_dialog_loop_and_action_use_selected_binding():
    from atlas_watchdog.qt import QAction, QApplication, QDialog, QTimer, LEGACY, exec_dialog
    app = QApplication.instance() or QApplication([])
    dialog = QDialog()
    QTimer.singleShot(0, dialog.accept)
    assert exec_dialog(dialog) == QDialog.DialogCode.Accepted
    assert QAction("test", dialog).text() == "test"
    forbidden = "PySide6" if LEGACY else "PySide2"
    assert not any(name == forbidden or name.startswith(forbidden + ".") for name in sys.modules)
    app.processEvents()


def load_packaging_common():
    path = Path(__file__).resolve().parents[1] / "packaging" / "common.py"
    spec = importlib.util.spec_from_file_location("watchdog_packaging_common", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("profile,binding,major", [("legacy", "PySide2", "5"), ("modern", "PySide6", "6")])
def test_packaging_keeps_required_widgets_and_rejects_qml(profile, binding, major):
    common = load_packaging_common()
    keep = [f"{binding}/Qt{major}Core.dll", f"{binding}/Qt{major}Gui.dll", f"{binding}/Qt{major}Widgets.dll",
            f"{binding}/Qt{major}Network.dll", f"{binding}/plugins/platforms/qwindows.dll",
            "vcruntime140.dll", "msvcp140.dll"]
    if profile == "legacy":
        keep.append(f"{binding}/Qt{major}Qml.dll")  # Required by pyside2.abi3.dll.
    drop = [f"{binding}/Qt{major}VirtualKeyboard.dll",
            f"{binding}/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll", f"{binding}/Qt{major}WebEngineCore.dll"]
    if profile == "modern":
        drop.append(f"{binding}/Qt{major}Qml.dll")
    entries = [(name, name, "BINARY") for name in keep + drop]
    assert [e[0] for e in common.widget_binaries(entries, profile)] == keep


def test_import_failure_returns_nonzero_without_qt_dialog(tmp_path, monkeypatch):
    from atlas_watchdog.__main__ import main
    import builtins
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["atlas-watchdog", "--smoke-test"])
    original = builtins.__import__
    def failing(name, *args, **kwargs):
        if name == "gui":
            raise ImportError("fake-password")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", failing)
    assert main() == 1
    report = json.loads((tmp_path / "ATLASWatchdog" / "startup.json").read_text())
    assert report["exception"] == "ImportError"
    assert "fake-password" not in json.dumps(report)
