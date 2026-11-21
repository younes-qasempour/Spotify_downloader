; Inno Setup 6 Script for Flacify v2.0
; Per-User Windows Installer bundling Tauri v2 Desktop App + FastAPI Backend Sidecar + Web UI

#define MyAppName "Flacify"
#define MyAppVersion "2.0.1"
#define MyAppPublisher "Flacify Project"
#define MyAppExeName "Flacify.exe"
#define MyAppBackendExe "binaries\flacify-backend\flacify-backend.exe"

[Setup]
; Preserve AppId so v1.x installs upgrade smoothly in place
AppId={{B310A74F-758B-4C23-8B35-C4F4E466371D}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}

PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

OutputDir=dist\installer
OutputBaseFilename=Flacify_Setup_v2.0.1
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

VersionInfoVersion=2.0.1.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Flacify v2.0.1 Lossless Audio Studio Setup
VersionInfoCopyright=Copyright (C) 2026 {#MyAppPublisher}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion=2.0.1.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\Flacify-v2\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autoprograms}\{#MyAppName} Web Server (LAN)"; Filename: "{app}\{#MyAppBackendExe}"; Parameters: "--host 0.0.0.0 --port 8765 --open"; IconFilename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

[UninstallDelete]
Type: files; Name: "{app}\*.log"
