# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller --noconfirm packaging/whm.spec

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# python-whois ships public_suffix_list.dat under whois/data — required if any
# code path still calls whois.extract_domain() inside a frozen build.
whois_datas = collect_data_files("whois")

a = Analysis(
    ['../src/whm/__main__.py'],
    pathex=['../src'],
    binaries=[],
    datas=[('../src/whm/presentation/web', 'whm/presentation/web')] + whois_datas,
    hiddenimports=[
        'whm',
        'whm.main',
        'whm.presentation.app',
        'whm.presentation.webapi',
        'whm.presentation.launcher',
        'whm.presentation.copy',
        'whm.application.services',
        'whm.application.scheduler',
        'whm.infrastructure.database',
        'whm.infrastructure.repositories',
        'whm.infrastructure.http_checker',
        'whm.infrastructure.ssl_checker',
        'whm.infrastructure.dns_checker',
        'whm.infrastructure.email_checker',
        'whm.infrastructure.whois_checker',
        'whm.infrastructure.reports',
        'whm.infrastructure.importer',
        'whm.infrastructure.notifications',
        'whm.infrastructure.fingerprint',
        'dns',
        'dns.resolver',
        'httpx',
        'httpcore',
        'certifi',
        'cryptography',
        'whois',
        'whois.whois',
        'whois.parser',
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
    icon='whm.ico',
)
