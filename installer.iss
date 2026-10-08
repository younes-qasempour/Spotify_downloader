; Inno Setup 6 Script for Flacify
; Production-Grade Per-User Windows Installer

#define MyAppName "Flacify"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "Flacify Project"
#define MyAppExeName "Flacify.exe"
#define MyAppMutex "FlacifyMutex"

[Setup]
; Unique Application ID
AppId={{B310A74F-758B-4C23-8B35-C4F4E466371D}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}

; Per-User Installation Mode (Lowest privilege into AppData/Programs)
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; Output Configuration
OutputDir=dist\installer
OutputBaseFilename=Flacify_Setup_v1.0.1
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; Compression Engine
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; 64-bit Windows Architecture
ArchitecturesInstallIn64BitMode=x64compatible

; Prevent installing or upgrading over an actively running instance
AppMutex={#MyAppMutex}

; Windows Add/Remove Programs Metadata
VersionInfoVersion=1.0.1.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Flacify High-Fidelity Audio Scraper Setup
VersionInfoCopyright=Copyright (C) 2026 {#MyAppPublisher}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion=1.0.1.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Dist folder contents produced by PyInstaller (onedir mode)
Source: "dist\Flacify\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up runtime log and temporary cache files left in install dir (if any)
Type: files; Name: "{app}\*.log"