; ============================================================================
; JobHunt — Inno Setup installer script
; ----------------------------------------------------------------------------
; Compiled by Inno Setup 6 (https://jrsoftware.org/isinfo.php).
; Driven by build.py — you generally shouldn't run ISCC directly; build.py
; passes the version and dist path as preprocessor defines so this one script
; works across every release.
;
; Output:
;   installer/Output/JobHunt-Setup-<version>.exe
;
; Install layout (on the user's machine):
;   C:\Program Files\JobHunt\JobHunt.exe
;   C:\Program Files\JobHunt\_internal\...   (PyInstaller runtime)
;   %APPDATA%\JobHunt\                       (per-user data — NOT touched by
;                                             the installer/uninstaller; the
;                                             app owns its data dir)
;
; Notes on /SILENT (used by the in-app auto-updater):
;   The updater spawns this installer with /SP- /SILENT /CLOSEAPPLICATIONS
;   /NORESTART. CloseApplications=force tells Inno to terminate the running
;   JobHunt.exe gracefully before overwriting it. RestartApplications=yes
;   then relaunches it after install. Combined, this gives the "click update,
;   app restarts on the new version, done" experience.
; ============================================================================

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\dist\JobHunt"
#endif

#define MyAppName      "JobHunt"
#define MyAppPublisher "The Scarlet Coder"
#define MyAppURL       "https://github.com/TheScarletEditor/JobHunt"
#define MyAppExeName   "JobHunt.exe"
; Stable AppId — DO NOT change between releases. This is what lets Inno Setup
; recognize "this is an upgrade of the same product" rather than installing
; a second copy alongside the old one. Kept verbatim through the v0.6.3
; "Scarlet Raven → Scarlet Coder" rename so existing 0.6.0–0.6.2 installs
; upgrade in place rather than installing alongside.
#define MyAppId        "{{A1B2C3D4-5E6F-4A8B-9C0D-1E2F3A4B5C6D}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=no
AllowNoIcons=yes

; 64-bit only — PySide6 wheels and Chromium are x64. The "x64compatible"
; identifier covers x64 and arm64-on-Windows-11 emulation.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Per-user install when not elevated; per-machine when run as admin. Friends
; double-clicking the .exe will hit a UAC prompt and install into Program
; Files. The auto-updater (which inherits the original install scope) will
; "just work" in both modes.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline

OutputDir=Output
OutputBaseFilename=JobHunt-Setup-{#AppVersion}
SetupIconFile=JobHunt.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#AppVersion}
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; ---------------------------------------------------------------------------
; Close + relaunch the running app on upgrade. This is what makes the
; in-app "Download & install" button feel native — JobHunt closes, gets
; overwritten, comes back up on the new version.
; ---------------------------------------------------------------------------
CloseApplications=force
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Note: Quick Launch task removed — Windows 7+ doesn't expose Quick Launch by
; default and Inno Setup's 6.1+ guard would skip it anyway.

[Files]
; The whole PyInstaller one-folder tree. recursesubdirs + createallsubdirs
; preserves the exact layout JobHunt.exe expects.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; postinstall + nowait so the wizard's "Finish" screen offers to launch
; JobHunt; skipifsilent so the auto-updater path doesn't trigger it twice
; (CloseApplications/RestartApplications handles that case instead).
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Wipe the install dir on uninstall in case stray Qt cache / PyInstaller
; tempfiles got dropped there. We deliberately do NOT touch %APPDATA%\JobHunt —
; that holds the user's database, resume drafts, and saved credentials. If
; they reinstall later, everything picks up where it left off.
Type: filesandordirs; Name: "{app}"
