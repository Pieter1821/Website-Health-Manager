; Inno Setup script — Website Health Manager
; Prerequisites: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; Build exe first:  pyinstaller --noconfirm packaging/whm.spec
; Then compile:     iscc packaging/whm-setup.iss
;
; Upgrades: same AppId replaces the previous install in place. No uninstall required.
; AppMutex must match CreateMutexW name in src/whm/main.py (_acquire_app_mutex).
; Before replacing files, [Code] force-kills WebsiteHealthManager.exe so upgrades
; do not hit DeleteFile code 5 (Access Denied) from leftover / child processes.

#define MyAppName "Website Health Manager"
#define MyAppShort "WHM"
#define MyAppVersion "0.1.8"
#define MyAppPublisher "WHM"
#define MyAppExeName "WebsiteHealthManager.exe"
#define MyAppMutex "WebsiteHealthManagerSingleInstance"

[Setup]
AppId={{A7C3E2F1-8B4D-4E9A-9C21-WHM0INSTALL01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppMutex={#MyAppMutex}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Reuse the previous install folder when the same AppId is found (upgrade in place).
UsePreviousAppDir=yes
; Do not scare users when the folder still exists after a messy uninstall / leftover files.
DirExistsWarning=no
; Backup if something is still holding files; primary unlock is taskkill in [Code].
CloseApplications=force
RestartApplications=yes
CloseApplicationsFilter=*.exe,*.dll
OutputDir=..\dist
OutputBaseFilename=WebsiteHealthManager-Setup-{#MyAppVersion}
SetupIconFile=whm.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
InfoBeforeFile=
LicenseFile=..\LICENSE
; Install for current user by default (no admin required).

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Files]
; ignoreversion: always replace on upgrade (PyInstaller builds often share similar PE versions).
; overwritereadonly: clear read-only attribute if a previous install left it set.
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion overwritereadonly

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Messages]
WelcomeLabel2=This will install Website Health Manager on your computer.%n%nIf an older copy is already installed, Setup upgrades it in place — you do not need to uninstall first.%n%nIf the app is open, Setup closes it automatically. After install, Chrome opens the WHM window. No Python is required.
FinishedLabel=Setup has finished installing Website Health Manager.%n%nYou can launch it from the Start menu or desktop shortcut.

[Code]
const
  AppImageName = '{#MyAppExeName}';

{ Force-terminate all WebsiteHealthManager.exe processes (including children). }
procedure KillAppProcesses;
var
  ResultCode: Integer;
begin
  { /T kills the process tree; /F forces termination. Exit code 128 = not found — fine. }
  Exec('taskkill.exe', '/F /IM ' + AppImageName + ' /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
  Exec('taskkill.exe', '/F /IM ' + AppImageName + ' /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
end;

{ Kill before Inno's CloseApplications scan so the Applications page usually stays empty. }
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then
    KillAppProcesses;
end;

{ Belt-and-suspenders: kill again right before file copy. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillAppProcesses;
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    KillAppProcesses;
end;
