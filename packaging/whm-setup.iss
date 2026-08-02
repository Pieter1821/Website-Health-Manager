; Inno Setup script — Website Health Manager
; Prerequisites: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; Build exe first:  pyinstaller --noconfirm packaging/whm.spec
; Then compile:     iscc packaging/whm-setup.iss

#define MyAppName "Website Health Manager"
#define MyAppShort "WHM"
#define MyAppVersion "0.1.5"
#define MyAppPublisher "WHM"
#define MyAppExeName "WebsiteHealthManager.exe"

[Setup]
AppId={{A7C3E2F1-8B4D-4E9A-9C21-WHM0INSTALL01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
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
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Messages]
WelcomeLabel2=This will install Website Health Manager on your computer.%n%nDouble-click the app after setup — Chrome opens the WHM window. No Python install is required.
FinishedLabel=Setup has finished installing Website Health Manager.%n%nYou can launch it from the Start menu or desktop shortcut.
