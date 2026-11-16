# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
import sys


project_root = Path(SPECPATH)

# Qt uses Windows' ICU. A third-party icuuc.dll earlier in PATH can be
# collected instead, causing "DLL load failed" even on the build machine.
if sys.platform == 'win32':
    system32 = str(Path(os.environ['SystemRoot']) / 'System32')
    os.environ['PATH'] = system32 + os.pathsep + os.environ.get('PATH', '')

a = Analysis(
    [str(project_root / 'main.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / 'configs' / 'annotation_modes' / '*.json'), 'configs/annotation_modes'),
        (str(project_root / 'configs' / 'user_preferences.json'), 'configs'),
        (str(project_root / 'assets'), 'assets'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LexiArbiter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project_root / 'assets' / 'LexiArbiter_icon.ico'),
    # app_root() reads editable configs and assets next to the executable.
    contents_directory='.',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LexiArbiter',
)
