; Custom Program Launcher - Inno Setup installer script
;
; HOW TO USE:
;   1. Build the app with PyInstaller in --onedir mode: dist\installer\ProgramLauncher\
;      (build.ps1 does this automatically, alongside the separate --onefile portable build)
;   2. Open this file in Inno Setup Compiler and press Compile (or F9).
;   3. The finished installer appears in the "Installer_Output" folder.
;
; RELEASING A NEW VERSION LATER:
;   - Edit version.txt (in this same folder) to the new version number, e.g. "1.1.0".
;     This one file is the single source of truth - launcher.py reads it too (shown in
;     the Settings menu), so the app and installer will always report the same version.
;   - Rebuild with PyInstaller (make sure version.txt is still bundled via --add-data,
;     same as app_icon.ico).
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
OutputDir=Installer_Output\v{#MyAppVersion}
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

[InstallDelete]
; Wipe the old _internal folder before copying the new one in. Without this,
; files that existed in an older version's onedir build but aren't part of a
; newer one would just be left behind forever, since Inno Setup only adds/
; overwrites files listed in [Files] - it never removes stale ones on its own.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\installer\ProgramLauncher\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent
