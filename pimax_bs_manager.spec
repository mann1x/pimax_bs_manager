# -*- mode: python ; coding: utf-8 -*-

block_cipher = None


a = Analysis(['C:/Users/manni/PycharmProjects/pimax_bs_manager'],
             pathex=['C:\\Users\\manni\\PycharmProjects\\pimax_bs_manager'],
             binaries=[('BleakUWPBridge.dll', 'BleakUWPBridge')],
             datas=[],
             hiddenimports=['pkg_resources', 'infi.systray', 'bleak'],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name='pimax_bs_manager',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=False , version='pimax_bsaw_version_info.txt', icon='pimax.ico')
