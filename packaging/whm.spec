# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller --noconfirm packaging/whm.spec

block_cipher = None

a = Analysis(
    ['../src/whm/__main__.py'],
    pathex=['../src'],
    binaries=[],
    datas=[('../src/whm/presentation/web', 'whm/presentation/web')],
    hiddenimports=[
        'whm',
        'whm.main',
        'whm.presentation.app',
        'dns',
        'httpx',
        'cryptography',
        'whois',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='WebsiteHealthManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
