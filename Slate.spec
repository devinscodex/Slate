# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_all

sys.path.insert(0, SPECPATH)
import version as slate_version  # noqa: E402


def _version_resource():
    """Windows VERSIONINFO for Slate.exe, so file properties name the
    product, publisher and license instead of showing blanks."""
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )
    v = slate_version.VERSION
    nums = tuple((int(p) for p in v.split(".")[:3])) + (0,) * (4 - len(v.split(".")[:3]))
    fields = [
        ("CompanyName", slate_version.AUTHOR),
        ("FileDescription", "Slate PDF editor"),
        ("FileVersion", v),
        ("InternalName", "Slate"),
        ("LegalCopyright", f"Copyright (c) 2026 {slate_version.AUTHOR}. {slate_version.LICENSE}"),
        ("OriginalFilename", "Slate.exe"),
        ("ProductName", "Slate"),
        ("ProductVersion", v),
        ("Comments", "https://github.com/devinscodex/Slate"),
    ]
    info = VSVersionInfo(
        ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004,
                          fileType=0x1, subtype=0x0, date=(0, 0)),
        kids=[
            StringFileInfo([StringTable("040904B0", [StringStruct(k, val) for k, val in fields])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )
    os.makedirs("build", exist_ok=True)
    path = os.path.join("build", "version_info.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(info))
    return path


datas = [('branding', 'branding'), ('theme_data', 'theme_data'), ('tessdata', 'tessdata')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('fitz')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# PyMuPDF split its real package out from the 'fitz' compat shim --
# 'fitz' is now 3 pure-Python files re-exporting 'from pymupdf import *';
# every compiled extension and data resource (including the layout-
# analysis ONNX model config fitz/pymupdf's own import chain pulls in
# at startup) lives under the separate top-level 'pymupdf' package.
# collect_all('fitz') alone misses all of it -- real frozen-exe crash,
# FileNotFoundError on a missing .../pymupdf/layout/resources/onnx/*.yaml,
# reproduced locally and confirmed fixed by also collecting 'pymupdf'.
tmp_ret = collect_all('pymupdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pikepdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyhanko')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# A Linux PyInstaller build crashes opening any real document with
# "ModuleNotFoundError: No module
# named 'PIL._tkinter_finder'" -- PIL/Pillow was never in this file's own
# collect_all list (only fitz/pikepdf/pyhanko), so PyInstaller's automatic
# PIL hook missed this specific helper module that ImageTk.PhotoImage needs
# at runtime to bridge into Tk's own C image extension. Harmless on Windows
# too (just ensures the same module ships there as well) -- not
# platform-specific, a real gap in what this spec collects.
hiddenimports += ['PIL._tkinter_finder']

a = Analysis(
    ['slate.py'],
    pathex=[],
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
    [],
    exclude_binaries=True,
    name='Slate',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX OFF -- a packed, unsigned EXE is a classic AV heuristic trigger
    # (malware uses the same packer to hide payloads; Defender and others
    # weight "compressed + no publisher signature" heavily). Larger binary,
    # far less suspicious. Real fix for the trojan false-positive, not a
    # workaround -- see codesign_identity below for the other real half.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['branding\\slate.ico'],
    version=_version_resource() if sys.platform == 'win32' else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,  # matches EXE() above -- same reasoning, same fix
    upx_exclude=[],
    name='Slate',
)
