#define AppVersion "0.7.2"
#define SourceRoot AddBackslash(SourcePath) + ".."
#define DistRoot SourceRoot + "\dist\portable"
#define OutputRoot SourceRoot + "\dist"
[Setup]
#ifdef TestBuild
AppId={{0B164BF7-11A3-4E12-AC18-703295D8505D}
#else
AppId={{F1C2AB73-4974-4A4D-84AA-389E4BB98126}
#endif
AppName=Antigravity 本地账号切换器
AppVersion={#AppVersion}
AppPublisher=Independent local utility
DefaultDirName={localappdata}\Programs\AntigravityLocalSwitcher
DefaultGroupName=Antigravity 本地账号切换器
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir={#OutputRoot}
OutputBaseFilename=AntigravityLocalSwitcher-Setup-v0.7.2
SetupIconFile={#SourceRoot}\assets\app-icon.ico
UninstallDisplayIcon={app}\AntigravityLocalSwitcher.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
SetupLogging=yes
#ifdef TestBuild
CreateUninstallRegKey=no
#endif
InfoBeforeFile={#DistRoot}\安装说明.txt
VersionInfoVersion={#AppVersion}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "{#DistRoot}\AntigravityLocalSwitcher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistRoot}\AntigravityLocalSwitcher.exe"; DestName: "UpgradeHelper.exe"; Flags: dontcopy
Source: "{#SourceRoot}\使用说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistRoot}\安装说明.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistRoot}\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs

Source: "{#DistRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistRoot}\SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistRoot}\README.en.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
#ifndef TestBuild
Name: "{group}\Antigravity 本地账号切换器"; Filename: "{app}\AntigravityLocalSwitcher.exe"; WorkingDir: "{app}"; IconFilename: "{app}\AntigravityLocalSwitcher.exe"
Name: "{userdesktop}\Antigravity 本地账号切换器"; Filename: "{app}\AntigravityLocalSwitcher.exe"; WorkingDir: "{app}"; IconFilename: "{app}\AntigravityLocalSwitcher.exe"; Tasks: desktopicon
Name: "{group}\卸载账号工具"; Filename: "{uninstallexe}"

#endif

[Run]
Filename: "{app}\AntigravityLocalSwitcher.exe"; Description: "打开 Antigravity 本地账号切换器"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var ExitCode: Integer;
begin
  Result := '';
  ExtractTemporaryFile('UpgradeHelper.exe');
  if not Exec(ExpandConstant('{tmp}\UpgradeHelper.exe'), '--stop-running', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Result := '无法启动旧后台退出助手，请关闭账号工具后重试。'
  else if ExitCode <> 0 then
    Result := '旧账号工具尚未退出，请等待当前保存或查询操作完成后重试。';
end;

function InitializeUninstall(): Boolean;
var ExitCode: Integer;
begin
  Result := True;
  if FileExists(ExpandConstant('{app}\AntigravityLocalSwitcher.exe')) then begin
    if not Exec(ExpandConstant('{app}\AntigravityLocalSwitcher.exe'), '--stop-running', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := False
    else
      Result := ExitCode = 0;
    if not Result then
      MsgBox('账号工具尚未正常退出，请稍后再卸载。账号快照会保留。', mbError, MB_OK);
  end;
end;
