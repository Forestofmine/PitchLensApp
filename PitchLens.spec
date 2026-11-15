# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a one-folder Windows build."""

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH)
datas = [
    (str(ROOT / "pitchlens" / "resources"), "pitchlens/resources"),
    (str(ROOT / "examples"), "examples"),
]
datas += collect_data_files("pyqtgraph")
hiddenimports = [
    "sounddevice",
    "scipy.signal",
    "scipy.signal._signaltools",
    "cv2",
    "pyqtgraph",
    "PIL.Image",
    "PIL.ImageDraw",
]

a = Analysis(
    ["run_pitchlens.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "torch",
        "onnxruntime",
        "torchcrepe",
        "matplotlib",
        "OpenGL",
        "pyqtgraph.opengl",
        "pyqtgraph.examples",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PitchLens",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "pitchlens" / "resources" / "app.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PitchLens",
)
