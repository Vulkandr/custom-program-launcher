; Custom Program Launcher - Inno Setup installer script
;
; HOW TO USE:
;   1. Build ProgramLauncher.exe with PyInstaller as usual (dist\ProgramLauncher.exe).
;   2. Open this file in Inno Setup Compiler and press Compile (or F9).
;   3. The finished installer appears in the "Installer_Output" folder.
;
; RELEASING A NEW VERSION LATER:
;   - Edit version.txt (in this same folder) to the new version number, e.g. "1.1.0".
;     This one file is the single source of truth - launcher.py reads it too (shown in
;     the Settings menu), so the app and installer will always report the same version.
;   - Rebuild ProgramLauncher.exe with PyInstaller (make sure version.txt is still bundled
;     via --add-data, same as app_icon.ico).
;   - Never change MyAppId - that's what lets a new installer recognize and cleanly
;     upgrade an existing install instead of creating a duplicate/second copy.
;   - Recompile this script. Give the new Setup exe to anyone who has an older version
;     installed; running it will upgrade them in place, in the same folder, with the
;     same Start Menu shortcut - no need to uninstall first.

#define MyAppName "Custom Program Launcher"
#define MyAppVersionFile FileOpen(AddBackslash(SourcePath) + "version.txt")
#define MyAppVersion Trim(FileRead(MyAppVersionFile))
#expr FileClose(MyAppVersionFile)
#define MyAppPublisher "Lukas"
#define MyAppExeName "ProgramLauncher.exe"
#define MyAppId "{{7B42AD87-7B8A-4719-85B7-178323BB821C}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
OutputDir=Installer_Output
OutputBaseFilename=CPL_Setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible

; Automatically closes the app if it's already running (e.g. during an upgrade),
; since Windows won't let us overwrite a running exe.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent
