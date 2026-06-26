# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None

import sys

# Python DLL 目录
python_dll_dir = os.path.join(os.path.dirname(sys.executable), 'DLLs')

a = Analysis(
    ['backend_packaged.py'],
    pathex=[],
    binaries=[
        (os.path.join(python_dll_dir, 'libcrypto-3.dll'), '.'),
        (os.path.join(python_dll_dir, 'libssl-3.dll'), '.'),
        (os.path.join(python_dll_dir, 'libffi-8.dll'), '.'),
    ],
    datas=[
        ('frontend-dist', 'frontend-dist'),
        ('install-chrome.ps1', '.'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'selenium',
        'selenium.webdriver',
        'selenium.webdriver.chrome',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.chrome.webdriver',
        'selenium.webdriver.edge',
        'selenium.webdriver.edge.options',
        'selenium.webdriver.edge.service',
        'selenium.webdriver.edge.webdriver',
        'selenium.webdriver.common',
        'selenium.webdriver.common.by',
        'selenium.webdriver.common.keys',
        'selenium.webdriver.common.service',
        'selenium.common',
        'selenium.common.exceptions',
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
    [],
    exclude_binaries=True,
    name='抖音火花助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='抖音火花助手',
)
