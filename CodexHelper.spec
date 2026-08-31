# -*- mode: python ; coding: utf-8 -*-
"""Codex 小帮手 打包配置（PyInstaller onefile + WebView2 窗口）。

⚠ 入口必须是 `codexhelper/__main__.py`（它指向 launcher / WebView2）。
   不要改回 node_codex_installer.py 或 app.py（tkinter 旧界面）。

为什么用 spec 而不是纯命令行：
  pywebview 依赖 clr_loader / pythonnet，且需要
  `webview.platforms.edgechromium` 等隐藏导入。命令行漏掉这些时，
  EXE 能启动但会静默退化成浏览器模式（不是原生窗口），
  这类问题在日志里只有一行"pywebview 不可用"，很容易被忽略。

路径一律相对 SPECPATH：
  早期版本硬编码了 F:/vibe code/... ，换台机器就构建失败。
  CI 里 `pyinstaller CodexHelper.spec` 才能开箱即用。
"""
import os

from PyInstaller.utils.hooks import collect_all

# SPECPATH = 本 spec 所在目录，构建时由 PyInstaller 注入
HERE = os.path.abspath(SPECPATH)  # noqa: F821

datas = []
binaries = []
hiddenimports = ['webview.platforms.edgechromium', 'webview.platforms.winforms']

# Node.js 安装包：可选。缺了只是无法一键装 Node，不影响打包。
# 依次在 spec 同级目录、上级目录里找。
msi_name = 'node-v24.18.0-x64.msi'
for cand in (os.path.join(HERE, msi_name),
             os.path.join(os.path.dirname(HERE), msi_name)):
    if os.path.isfile(cand):
        datas.append((cand, 'assets'))
        break
else:
    print(f'[spec] 警告：未找到 {msi_name}，打包后无法一键安装 Node')

for name in ('installer.ico', 'codex_helper.ico'):
    p = os.path.join(HERE, name)
    if os.path.isfile(p):
        datas.append((p, 'assets'))

for pkg in ('webview', 'clr_loader', 'pythonnet'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass  # 缺失时按浏览器模式回退，不阻断打包

a = Analysis(
    [os.path.join(HERE, 'codexhelper', '__main__.py')],
    pathex=[HERE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='Codex小帮手',
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
    version=os.path.join(HERE, 'version_info.txt'),
    icon=[os.path.join(HERE, 'installer.ico')],
)
