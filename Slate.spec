# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('branding', 'branding'), ('theme_data', 'theme_data'), ('tessdata', 'tessdata')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('fitz')
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
