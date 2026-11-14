# Build on Windows: .venv\Scripts\python.exe -m PyInstaller packaging\onedir.spec --noconfirm
from pathlib import Path
import sys
root = Path(SPECPATH).parent
sys.path.insert(0, str(root / "packaging"))
from common import bundle_data, widget_binaries, EXCLUDES

a = Analysis([str(root / "packaging" / "entry.py")], pathex=[str(root / "src")],
             binaries=[], datas=bundle_data(root),
             hiddenimports=["PySide6.QtNetwork"], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=EXCLUDES, noarchive=False)
a.binaries = widget_binaries(a.binaries)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ATLASWatchdog-debug",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ATLASWatchdog-debug")
