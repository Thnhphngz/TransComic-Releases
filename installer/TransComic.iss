#define MyAppName "TransComic"
#ifndef BUILD_LOCAL
  #error Stage A locked: only authorized BUILD_LOCAL compilation is enabled
#endif
; Stage B generates this include from transcomic/version.py.
#include "generated-version.iss"
#define MyAppExeName "TransComic.exe"

[Setup]
AppId={{CB58C770-47B7-42DC-A2CA-409DDF456487}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\installer\output
OutputBaseFilename=TransComic-Setup-{#MyAppVersion}-windows-x64
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
MinVersion=10.0
RestartIfNeededByRun=no
CloseApplications=no
RestartApplications=no
AppMutex=TransComic.Desktop.Running
UsePreviousAppDir=yes
SetupIconFile=TransComic.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion={#MyAppVersion}
InfoBeforeFile=..\docs\windows-distribution-rights.md

[Files]
; External shared libraries remain replaceable, including LGPL Qt/audio libraries.
Source: "..\dist\TransComic\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\TransComic-UpdateHelper.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Tạo biểu tượng Desktop"; GroupDescription: "Biểu tượng bổ sung:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Mở {#MyAppName}"; Flags: nowait postinstall skipifsilent
