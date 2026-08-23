# -*- mode: python ; coding: utf-8 -*-
# PyInstaller ビルド定義。Windows実機（またはGitHub Actionsのwindows-latest）で実行する。
#
#   pyinstaller pyenv_panel.spec
#
# 生成物: dist/PyEnvPanel.exe （単一exe、コンソールなし）
#
# 注意: このspecはWindows上でのみ意味を持つ（他OS向けバイナリは作れない）。
# 開発機がmac/Linuxの場合は、GitHub Actions（.github/workflows/build.yml）か
# 実機のWindows環境で実行すること。

import sys

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PyEnvPanel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUIアプリなのでコンソールウィンドウを出さない
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='packaging/version_info.txt' if sys.platform == 'win32' else None,
    icon='packaging/app.ico' if sys.platform == 'win32' else None,
)
