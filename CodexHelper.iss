; Codex 小帮手 安装脚本（Inno Setup 6）
;
; 编译：ISCC.exe CodexHelper.iss
; 产出：Output\CodexHelper-Setup-1.8.0.exe
;
; 设计要点
; --------
; 1. 安装到 {autopf}（Program Files），符合 Windows 惯例，卸载走"应用和功能"。
; 2. **VC++ 运行库在安装阶段就装上**：它是 pywebview/pythonnet 的原生依赖，
;    缺失会导致程序根本起不来——那时运行时提示也没机会显示。
; 3. WebView2 与 Python Manager 留给程序运行时提示安装：
;    它们缺失时程序仍能启动（只是降级），交给用户决定更合适。
; 4. deps 目录一起装进去，保证运行时提示能离线安装，不依赖网络。

#define MyAppName "Codex 小帮手"
#define MyAppVersion "1.8.2"
#define MyAppPublisher "小枳ai分享"
#define MyAppURL "https://github.com/Xiao-zhiii/CodexHelper"
#define MyAppExeName "Codex小帮手.exe"
#define DepsDir "..\deps"

[Setup]
AppId={{8E7A1F2C-4B6D-4E9A-9C3F-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; 安装包自带依赖，体积大，用管理员权限安装
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=CodexHelper-Setup-{#MyAppVersion}
SetupIconFile=installer.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
; 中文界面
WizardStyle=modern
WizardSizePercent=110
; 允许在 Win10/11 上正常显示
DisableDirPage=auto
DisableProgramGroupPage=auto
LicenseFile=
; 卸载时保留用户数据（日志、配置）
UninstallFilesDir={app}
; 装完不自动重启（VC++ 可能要求重启，让用户自己决定）
RestartIfNeededByRun=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
; 只保留桌面快捷方式。
; 快速启动栏（userappdata）在 Win10/11 上已基本弃用，
; 且它属于 per-user 区域，与管理员安装模式混用会触发
; UsedUserAreasWarning 并把快捷方式装到"管理员"用户目录下——
; 用户自己的快速启动栏里根本不会出现。
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
; 主程序（由 PyInstaller 打出的单文件 exe）
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; 运行时依赖安装包（供程序运行时提示离线安装）
Source: "{#DepsDir}\*"; DestDir: "{app}\deps"; Flags: ignoreversion recursesubdirs createallsubdirs

; 图标资源
Source: "installer.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "codex_helper.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; VC++ 运行库：静默安装，装完继续。
; 用 /norestart 避免中途重启打断安装流程。
; 已安装时安装程序会自行跳过，不会报错。
Filename: "{app}\deps\VC_redist.x64.exe"; \
  Parameters: "/quiet /norestart"; \
  StatusMsg: "正在安装 VC++ 运行库 (x64)…"; \
  Flags: waituntilterminated skipifdoesntexist; \
  Check: not VCRedistInstalled

; 装完询问是否立即启动
Filename: "{app}\{#MyAppExeName}"; \
  Description: "立即运行 {#MyAppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清掉程序目录残留（deps 由 Files 跟踪，会自动删）
Type: filesandordirs; Name: "{app}"

[Code]
{ 检测 VC++ 是否已安装：注册表 VisualStudio\14.0\VC\Runtimes\x64 下 Installed=1 }
function VCRedistInstalled: Boolean;
var
  Installed: Cardinal;
begin
  Result := False;
  if RegQueryDWordValue(HKEY_LOCAL_MACHINE,
       'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
       'Installed', Installed) then
  begin
    Result := (Installed = 1);
  end;
  { 64 位系统上也可能装在 WOW6432Node，一并检查 }
  if (not Result) and RegQueryDWordValue(HKEY_LOCAL_MACHINE,
       'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64',
       'Installed', Installed) then
  begin
    Result := (Installed = 1);
  end;
end;

{ 安装前提示：让用户知道会装额外组件。
  ⚠ 静默模式（/VERYSILENT）下绝不能弹 MsgBox——
  没有人能点按钮，安装/卸载会一直挂起到超时。
  自动化部署与 CI 都跑静默模式，这里必须放行。 }
function InitializeSetup(): Boolean;
begin
  Result := True;
  if WizardSilent() then
    exit;
  if not VCRedistInstalled then
  begin
    if MsgBox('本程序需要 VC++ 运行库 (x64)，安装程序将一并安装。' + #13#10 +
              '是否继续？',
              mbInformation, MB_YESNO) = IDNO then
    begin
      Result := False;
    end;
  end;
end;

{ 卸载前确认，避免误删。静默模式同样直接放行。 }
function InitializeUninstall(): Boolean;
begin
  if WizardSilent() then
  begin
    Result := True;
    exit;
  end;
  Result := MsgBox('确定要卸载 ' + '{#MyAppName}' + ' 吗？' + #13#10 +
                   '用户数据与设置将保留。',
                   mbConfirmation, MB_YESNO) = IDYES;
end;
