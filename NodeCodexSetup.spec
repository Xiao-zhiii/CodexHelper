# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['F:/vibe code/src/node_codex_installer.py'],
    pathex=[],
    binaries=[],
    datas=[('F:/vibe code/node-v24.18.0-x64.msi', 'assets'), ('F:/vibe code/src/installer.ico', 'assets')],
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
    name='NodeCodexSetup',
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
    version='F:\\vibe code\\src\\version_info.txt',
    icon=['F:\\vibe code\\src\\installer.ico'],
)
