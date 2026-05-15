# PyInstaller spec — CLI headless (memovipro-run.exe)
#
# Construye:
#   pyinstaller memovipro-run.spec --clean
# Resultado en:
#   dist/memovipro-run.exe
#
# Pensado para ser invocado por Task Scheduler o por RunMacro.ps1.

# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['cli.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config.json', '.'),
        ('macros', 'macros'),
        ('pipelines', 'pipelines'),
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
    excludes=['PyQt6'],  # CLI no usa la GUI
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='memovipro-run',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # mostrar la consola para que se vean los logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
