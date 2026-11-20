; Optional Inno Setup script.
; Build the portable folder first with build.ps1, then compile this file with
; Inno Setup 6 (ISCC.exe installer.iss).

#define MyAppName "PitchLens 音准镜"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "PitchLens"
#define MyAppExeName "PitchLens.exe"

[Setup]
AppId={{8E0B17C8-4FA1-4C1D-9A8F-51A2A7B7B7A1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PitchLens
DefaultGroupName=PitchLens
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=PitchLens-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=pitchlens\resources\app.ico

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Files]
Source: "dist\PitchLens\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\PitchLens"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 PitchLens"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PitchLens"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 PitchLens"; Flags: nowait postinstall skipifsilent
