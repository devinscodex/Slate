; Slate installer (Inno Setup 6). Devin, 2026-07-25: "build the full
; installer." Wraps the PyInstaller --onedir output (dist\Slate\) --
; real Start Menu + optional Desktop shortcut, a real uninstaller
; (Inno Setup provides this automatically, no extra code needed), and
; OPTIONAL .pdf/.epub file-association registration (a Task checkbox,
; not forced -- overriding someone else's existing default PDF viewer
; unprompted would be rude on a shared/MEG machine, even though Devin
; himself wants Slate as his own default).
;
; Build: run this file through ISCC.exe (Inno Setup's own compiler) --
; requires dist\Slate\ to already exist (run PyInstaller first).

#define MyAppName "Slate"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "devinscodex"
#define MyAppExeName "Slate.exe"

[Setup]
AppId={{B4E1B4A0-6F1E-4A6C-9C1A-7D8E5F3A2B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=Slate-Setup-{#MyAppVersion}
SetupIconFile=..\branding\slate.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; No admin rights forced -- installs to the user's own profile by
; default via {autopf} resolving appropriately; PrivilegesRequired
; lowest lets a non-admin MEG user install it too, matching the
; eventual multi-user goal (feedback-cairn-slate-suckless-link memory).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "pdfassoc"; Description: "Set Slate as the default app for &PDF files"; GroupDescription: "File associations:"; Flags: unchecked
Name: "epubassoc"; Description: "Set Slate as the default app for &EPUB files"; GroupDescription: "File associations:"; Flags: unchecked

[Files]
; The whole PyInstaller --onedir output, recursively -- exe + all
; bundled deps/data (branding, both bundled TTS voices, etc.).
Source: "..\dist\Slate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; PDF association -- only written if the pdfassoc task is checked.
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "SlatePDF"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\SlatePDF"; ValueType: string; ValueName: ""; ValueData: "Slate PDF Document"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\SlatePDF\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: pdfassoc
Root: HKCU; Subkey: "Software\Classes\SlatePDF\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: pdfassoc

; EPUB association -- same pattern, separate task.
Root: HKCU; Subkey: "Software\Classes\.epub\OpenWithProgids"; ValueType: string; ValueName: "SlateEPUB"; ValueData: ""; Flags: uninsdeletevalue; Tasks: epubassoc
Root: HKCU; Subkey: "Software\Classes\SlateEPUB"; ValueType: string; ValueName: ""; ValueData: "Slate EPUB Document"; Flags: uninsdeletekey; Tasks: epubassoc
Root: HKCU; Subkey: "Software\Classes\SlateEPUB\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: epubassoc
Root: HKCU; Subkey: "Software\Classes\SlateEPUB\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: epubassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
