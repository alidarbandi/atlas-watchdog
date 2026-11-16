# Windowed portable build. Source/build instructions accompany distribution for Qt replacement.
from pathlib import Path
import sys
root = Path(SPECPATH).parent
sys.path.insert(0, str(root / "packaging"))
from common import bundle_data, widget_binaries, EXCLUDES, BINDING, ARTIFACT, profile_hook, profile_binaries

a = Analysis([str(root / "packaging" / "entry.py")], pathex=[str(root / "src")],
             binaries=profile_binaries(), datas=bundle_data(root),
             hiddenimports=[BINDING + ".QtNetwork"], hookspath=[], hooksconfig={},
             runtime_hooks=[profile_hook(root)], excludes=EXCLUDES, noarchive=False)
a.binaries = widget_binaries(a.binaries)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=ARTIFACT,
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
