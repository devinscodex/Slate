; Slate installer (Inno Setup 6). Wraps the PyInstaller --onedir output
; (dist\Slate\) -- Start Menu + optional Desktop shortcut, an
; uninstaller (Inno Setup provides this automatically), and
; file-association registration for every format Slate opens (a Task
; checkbox per group). Grouped by risk, checked state set per group
; accordingly: PDF/EPUB/images/code stay unchecked -- these formats
; commonly already have an established default app (a PDF reader, an
; IDE), so registering them is opt-in. Other documents/ebooks (.txt,
; .md, .mobi, .fb2, .cbz) and HTML default CHECKED -- a document reader
; not handling these would be the more surprising default. See
; slate.py's _open_document + CODE_TEXT_EXTENSIONS for the format list
; this mirrors. A "select all" checkbox above the Tasks list ([Code]
; section below) toggles every file-association task at once.
;
; Build: run this file through ISCC.exe (Inno Setup's own compiler) --
; requires dist\Slate\ to already exist (run PyInstaller first).

#define MyAppName "Slate"
; Overridable via ISCC's /DMyAppVersion=X.Y.Z (build-installer.ps1 passes
; version.py's real VERSION this way) so the two never drift apart --
; a hardcoded value here would silently lie about what the installer
; actually ships the moment version.py moves on without it.
#ifndef MyAppVersion
  #define MyAppVersion "1.1.0"
#endif
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
; lowest lets a non-admin user install it too.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "pdfassoc"; Description: "Set Slate as the default app for &PDF files"; GroupDescription: "File associations:"; Flags: unchecked
Name: "epubassoc"; Description: "Set Slate as the default app for &EPUB files"; GroupDescription: "File associations:"; Flags: unchecked
Name: "docassoc"; Description: "Make Slate available for other document/ebook files (.txt, .md, .mobi, .fb2, .cbz)"; GroupDescription: "File associations:"
Name: "imageassoc"; Description: "Make Slate available for image files (.png, .jpg, .jpeg, .gif, .bmp, .tiff, .heic)"; GroupDescription: "File associations:"; Flags: unchecked
Name: "htmlassoc"; Description: "Make Slate available for HTML files (.html, .htm)"; GroupDescription: "File associations:"
Name: "codeassoc"; Description: "Make Slate available for code/config files (.py, .js, .ts, .json, .yaml, .yml, .c, .h, .cpp, .cs, .go, .rs, .css, .sql, .ini, .cfg, .sh, .ps1)"; GroupDescription: "File associations:"; Flags: unchecked

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

; Other document/ebook formats -- one shared ProgId (SlateDoc), same
; command, registered against every extension in the group. Mirrors
; slate.py's _open_document else-branch (fitz.open natively handles
; txt/md/mobi/fb2/cbz with no conversion step, same as pdf).
Root: HKCU; Subkey: "Software\Classes\SlateDoc"; ValueType: string; ValueName: ""; ValueData: "Slate Document"; Flags: uninsdeletekey; Tasks: docassoc
Root: HKCU; Subkey: "Software\Classes\SlateDoc\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: docassoc
Root: HKCU; Subkey: "Software\Classes\SlateDoc\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: docassoc
Root: HKCU; Subkey: "Software\Classes\.txt\OpenWithProgids"; ValueType: string; ValueName: "SlateDoc"; ValueData: ""; Flags: uninsdeletevalue; Tasks: docassoc
Root: HKCU; Subkey: "Software\Classes\.md\OpenWithProgids"; ValueType: string; ValueName: "SlateDoc"; ValueData: ""; Flags: uninsdeletevalue; Tasks: docassoc
Root: HKCU; Subkey: "Software\Classes\.mobi\OpenWithProgids"; ValueType: string; ValueName: "SlateDoc"; ValueData: ""; Flags: uninsdeletevalue; Tasks: docassoc
Root: HKCU; Subkey: "Software\Classes\.fb2\OpenWithProgids"; ValueType: string; ValueName: "SlateDoc"; ValueData: ""; Flags: uninsdeletevalue; Tasks: docassoc
Root: HKCU; Subkey: "Software\Classes\.cbz\OpenWithProgids"; ValueType: string; ValueName: "SlateDoc"; ValueData: ""; Flags: uninsdeletevalue; Tasks: docassoc

; Image formats -- routed through convert.path_to_pdf first
; (slate.py _open_document), but the OS association only needs to
; launch Slate.exe with the original path; Slate does the conversion
; itself once opened.
Root: HKCU; Subkey: "Software\Classes\SlateImage"; ValueType: string; ValueName: ""; ValueData: "Slate Image Document"; Flags: uninsdeletekey; Tasks: imageassoc
Root: HKCU; Subkey: "Software\Classes\SlateImage\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: imageassoc
Root: HKCU; Subkey: "Software\Classes\SlateImage\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: imageassoc
Root: HKCU; Subkey: "Software\Classes\.png\OpenWithProgids"; ValueType: string; ValueName: "SlateImage"; ValueData: ""; Flags: uninsdeletevalue; Tasks: imageassoc
Root: HKCU; Subkey: "Software\Classes\.jpg\OpenWithProgids"; ValueType: string; ValueName: "SlateImage"; ValueData: ""; Flags: uninsdeletevalue; Tasks: imageassoc
Root: HKCU; Subkey: "Software\Classes\.jpeg\OpenWithProgids"; ValueType: string; ValueName: "SlateImage"; ValueData: ""; Flags: uninsdeletevalue; Tasks: imageassoc
Root: HKCU; Subkey: "Software\Classes\.gif\OpenWithProgids"; ValueType: string; ValueName: "SlateImage"; ValueData: ""; Flags: uninsdeletevalue; Tasks: imageassoc
Root: HKCU; Subkey: "Software\Classes\.bmp\OpenWithProgids"; ValueType: string; ValueName: "SlateImage"; ValueData: ""; Flags: uninsdeletevalue; Tasks: imageassoc
Root: HKCU; Subkey: "Software\Classes\.tiff\OpenWithProgids"; ValueType: string; ValueName: "SlateImage"; ValueData: ""; Flags: uninsdeletevalue; Tasks: imageassoc
Root: HKCU; Subkey: "Software\Classes\.heic\OpenWithProgids"; ValueType: string; ValueName: "SlateImage"; ValueData: ""; Flags: uninsdeletevalue; Tasks: imageassoc

; HTML -- also routed through convert.path_to_pdf, own checkbox since
; overriding a browser association is a bigger ask than an image
; viewer or text editor.
Root: HKCU; Subkey: "Software\Classes\SlateHTML"; ValueType: string; ValueName: ""; ValueData: "Slate HTML Document"; Flags: uninsdeletekey; Tasks: htmlassoc
Root: HKCU; Subkey: "Software\Classes\SlateHTML\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: htmlassoc
Root: HKCU; Subkey: "Software\Classes\SlateHTML\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: htmlassoc
Root: HKCU; Subkey: "Software\Classes\.html\OpenWithProgids"; ValueType: string; ValueName: "SlateHTML"; ValueData: ""; Flags: uninsdeletevalue; Tasks: htmlassoc
Root: HKCU; Subkey: "Software\Classes\.htm\OpenWithProgids"; ValueType: string; ValueName: "SlateHTML"; ValueData: ""; Flags: uninsdeletevalue; Tasks: htmlassoc

; Code/config text formats -- mirrors CODE_TEXT_EXTENSIONS in slate.py
; exactly; keep both lists in sync if that tuple ever changes.
Root: HKCU; Subkey: "Software\Classes\SlateCode"; ValueType: string; ValueName: ""; ValueData: "Slate Code/Text Document"; Flags: uninsdeletekey; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\SlateCode\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\SlateCode\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.ps1\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.py\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.sh\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.js\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.ts\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.json\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.yaml\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.yml\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.c\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.h\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.cpp\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.cs\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.go\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.rs\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.css\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.sql\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.ini\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc
Root: HKCU; Subkey: "Software\Classes\.cfg\OpenWithProgids"; ValueType: string; ValueName: "SlateCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: codeassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  SelectAllAssocCheckBox: TNewCheckBox;

// Every file-association Task's Description contains "files" (PDF
// files/EPUB files/document...files/image files/HTML files/code...
// files); the desktop-shortcut task and any GroupDescription header
// row do not, so this identifies the association group without
// depending on fixed list indices.
procedure SelectAllAssocClick(Sender: TObject);
var
  i: Integer;
begin
  for i := 0 to WizardForm.TasksList.Items.Count - 1 do
    if Pos('files', WizardForm.TasksList.Items[i]) > 0 then
      WizardForm.TasksList.Checked[i] := SelectAllAssocCheckBox.Checked;
end;

procedure InitializeWizard;
var
  ShiftAmount: Integer;
begin
  ShiftAmount := ScaleY(21);
  SelectAllAssocCheckBox := TNewCheckBox.Create(WizardForm);
  SelectAllAssocCheckBox.Parent := WizardForm.TasksList.Parent;
  SelectAllAssocCheckBox.Left := WizardForm.TasksList.Left;
  SelectAllAssocCheckBox.Top := WizardForm.TasksList.Top;
  SelectAllAssocCheckBox.Width := WizardForm.TasksList.Width;
  SelectAllAssocCheckBox.Height := ScaleY(17);
  SelectAllAssocCheckBox.Caption := 'Select all file formats below';
  SelectAllAssocCheckBox.OnClick := @SelectAllAssocClick;

  WizardForm.TasksList.Top := WizardForm.TasksList.Top + ShiftAmount;
  WizardForm.TasksList.Height := WizardForm.TasksList.Height - ShiftAmount;
end;
