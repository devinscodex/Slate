# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# voices/ (bundled TTS model) and the piper/onnxruntime/sounddevice/
# soundfile collect_all calls below are deliberately OFF -- Read Aloud is
# excluded from this build entirely (tts.ENGINE_AVAILABLE gates the UI in
# slate.py) to keep the binary lean. Re-enable by un-commenting these four
# lines, adding back ('voices', 'voices') to datas, and dropping the
# excludes= entries below -- nothing else needs to change, tts.py's own
# lazy-import already tolerates either state.
datas = [('branding', 'branding'), ('theme_data', 'theme_data')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('fitz')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pikepdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyhanko')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# tmp_ret = collect_all('piper')
# datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# tmp_ret = collect_all('onnxruntime')
# datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# tmp_ret = collect_all('sounddevice')
# datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# tmp_ret = collect_all('soundfile')
# datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# A Linux PyInstaller build crashes opening any real document with
# "ModuleNotFoundError: No module
# named 'PIL._tkinter_finder'" -- PIL/Pillow was never in this file's own
# collect_all list (only fitz/pikepdf/pyhanko/piper/onnxruntime/
# sounddevice/soundfile), so PyInstaller's automatic PIL hook missed this
# specific helper module that ImageTk.PhotoImage needs at runtime to
# bridge into Tk's own C image extension. Harmless on Windows too (just
# ensures the same module ships there as well) -- not platform-specific,
# a real gap in what this spec collects.
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
    # tts.py imports piper (and transitively onnxruntime/sounddevice) at
    # its own module level, guarded by a real try/except ImportError --
    # PyInstaller's static Analysis finds that import regardless of the
    # runtime guard and bundles it + everything it pulls in (~35MB:
    # onnxruntime 34.55MB, piper 0.48MB, _sounddevice_data 0.62MB),
    # completely undoing the collect_all() calls already commented out
    # above for the same reason. This is the other half of that same
    # intent, actually enforced -- ImportError at runtime is the designed
    # fallback (tts.py's own comment), ENGINE_AVAILABLE just becomes
    # False, no crash. Remove all four names together if Read Aloud ever
    # comes back (matching the collect_all block above).
    excludes=['piper', 'onnxruntime', 'sounddevice', 'soundfile'],
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
    strip=True,
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
    strip=True,
    upx=False,  # matches EXE() above -- same reasoning, same fix
    upx_exclude=[],
    name='Slate',
)
