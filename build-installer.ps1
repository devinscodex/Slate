# Slate rebuild + reinstall (Devin, 2026-07-26: "do this each time you
# update Slate"). Freezes slate.py with PyInstaller, compiles the Inno
# Setup installer, closes any running instance, and silently
# reinstalls over the Start Menu / AppData\Local\Programs copy so that
# shortcut always launches whatever's currently in slate.py.
#
# Usage: powershell.exe -ExecutionPolicy Bypass -File build-installer.ps1
param(
    [switch]$SkipInstall
)
# Deliberately NOT $ErrorActionPreference = "Stop" -- pip/PyInstaller/
# ISCC all write normal progress/warning text to stderr as part of
# ordinary operation, and Stop treats ANY stderr output from a native
# command as fatal (Cairn's own gotchas.md, hit live building this).
# Real failures are caught explicitly below via $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

# MUST use .venv-win's python, not bare `python` off PATH -- `where
# python` resolves to a nearly-empty standalone Python312 install
# (only PyInstaller/pipx tooling, none of Slate's real deps). Real
# gap caught live 2026-07-26: a build using the wrong interpreter
# "succeeded" (PyInstaller silently reused stale cached Analysis
# artifacts from an earlier correct build for modules it couldn't
# find fresh) and produced a Frankenstein EXE that crashed on launch
# with "cannot import name '_as_fz_document' from 'pymupdf'" -- a
# version-mismatched fitz/pymupdf binary, not a real code bug.
# .venv-win (Lib\site-packages has fitz/pymupdf/pikepdf/pyhanko/
# piper/onnxruntime all present) is the real, complete build env.
$venvPython = Join-Path $PSScriptRoot ".venv-win\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { throw ".venv-win not found at $venvPython -- real build env missing" }

Write-Host "=== 1/4: ensure PyInstaller available (.venv-win) ==="
& $venvPython -m pip install pyinstaller --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed (exit $LASTEXITCODE)" }

Write-Host "=== 2/4: freeze with PyInstaller (Slate.spec) ==="
# Clear any stale build/ cache -- PyInstaller reuses cached Analysis
# results per-module across runs; a prior run against the wrong
# interpreter could otherwise leave stale artifacts for this run to
# silently reuse instead of failing loudly.
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
& $venvPython -m PyInstaller Slate.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Write-Host "=== 3/4: compile installer (Inno Setup) ==="
$iscc = "C:\Users\devin\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source } else { throw "ISCC.exe not found -- Inno Setup 6 expected at $iscc" }
}
& $iscc "installer\slate.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC.exe failed (exit $LASTEXITCODE)" }

Write-Host "=== 4/4: reinstall ==="
if ($SkipInstall) {
    Write-Host "Skipping install (-SkipInstall passed) -- installer built, not run."
} else {
    Get-Process Slate -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 1
    $setupExe = Get-ChildItem "dist-installer\Slate-Setup-*.exe" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $setupExe) { throw "No Slate-Setup-*.exe found in dist-installer\" }
    Write-Host "Running $($setupExe.Name) /VERYSILENT /NORESTART ..."
    Start-Process -FilePath $setupExe.FullName -ArgumentList "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES" -Wait
    Write-Host "Reinstalled. New Slate.exe timestamp:"
    (Get-Item "$env:LOCALAPPDATA\Programs\Slate\Slate.exe").LastWriteTime

    # Real smoke test, not a blind "exit 0 = done" (a real gap caught
    # live 2026-07-26: a prior rebuild "succeeded" per every exit code
    # in this script yet crashed on first launch with an ImportError --
    # a version-mismatched fitz/pymupdf binary from a stale build
    # cache). Launches hidden (never a visible window, per Devin's
    # standing "don't flash Slate on my desktop" rule) with no file
    # argument, waits briefly, and checks whether it's still running
    # (real success) vs already exited (a launch-time crash, most
    # likely an unhandled Tkinter exception dialog same as this one).
    Write-Host "=== smoke test (hidden launch, no visible window) ==="
    $exePath = "$env:LOCALAPPDATA\Programs\Slate\Slate.exe"
    $proc = Start-Process -FilePath $exePath -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 4
    $stillRunning = -not $proc.HasExited
    if ($stillRunning) {
        Write-Host "OK -- Slate.exe still running after 4s, no immediate crash."
        Stop-Process -Id $proc.Id -Force
    } else {
        Write-Host "FAIL -- Slate.exe exited within 4s (exit code $($proc.ExitCode)) -- likely crashed on launch."
        throw "Smoke test failed: Slate.exe exited immediately after launch"
    }
}
Write-Host "=== done ==="
