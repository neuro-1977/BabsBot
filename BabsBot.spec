# -*- mode: python ; coding: utf-8 -*-
import os
_spec_dir = os.getcwd()
_datas = []
for _name in ('icon.ico', 'logo.png'):
    if os.path.isfile(os.path.join(_spec_dir, _name)):
        _datas.append((_name, '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BabsBot',
    icon='icon.ico' if os.path.isfile(os.path.join(_spec_dir, 'icon.ico')) else None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
