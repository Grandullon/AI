# PyInstaller spec — GUI (memovipro-gui.exe)
#
# Construye:
#   pyinstaller memovipro-gui.spec --clean
# Resultado en:
#   dist/memovipro-gui.exe

# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.json', '.'),
        ('macros', 'macros'),
    ],
    hiddenimports=[
        'pywinauto',
        'pywinauto.controls.uiawrapper',
        'pywinauto.controls.uia_controls',
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='memovipro-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI sin ventana de consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
