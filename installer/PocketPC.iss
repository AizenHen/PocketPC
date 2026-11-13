#define MyAppName "PocketPC"
#define MyAppVersion "1.7.0"
#define MyAppPublisher "PocketPC"
#define MyAppExeName "PocketPC.exe"

[Setup]
AppId={{9A2C02D9-8958-4F83-964B-98ED71B1526A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PocketPC
DefaultGroupName=PocketPC
DisableDirPage=no
OutputDir=..\release
OutputBaseFilename=PocketPC-Setup-{#MyAppVersion}
SetupIconFile=..\assets\pocketpc.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes

[Files]
Source: "..\dist\PocketPC\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\PocketPCInput.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\configure-installed.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\check-tailscale.ps1"; Flags: dontcopy

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal\frontend\dist"

[Tasks]
Name: "desktopicon"; Description: "Create a PocketPC shortcut on my desktop"; GroupDescription: "Shortcuts:"; Flags: checkedonce

[Icons]
Name: "{group}\PocketPC"; Filename: "{app}\PocketPC.exe"
Name: "{userdesktop}\PocketPC"; Filename: "{app}\PocketPC.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PocketPC.exe"; Description: "Launch PocketPC"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Get-NetFirewallRule -Name 'PocketPC-Installed-STUN','PocketPC-Installed-WebRTC' -ErrorAction SilentlyContinue | Remove-NetFirewallRule"""; Flags: runhidden waituntilterminated; RunOnceId: "RemovePocketPCFirewallRules"

[Code]
var
  TailscalePage: TWizardPage;
  TailscaleStatus: TNewStaticText;
  TailscaleReady: Boolean;
  ConfigurationSucceeded: Boolean;

procedure SetStatus(const MessageText: String; IsReady: Boolean);
begin
  TailscaleReady := IsReady;
  TailscaleStatus.Caption := MessageText;
  if IsReady then
    TailscaleStatus.Font.Color := $0068C58C
  else
    TailscaleStatus.Font.Color := $005D91E8;
end;

function CheckTailscale: Boolean;
var
  ResultCode: Integer;
  CheckerPath: String;
begin
  Result := False;
  SetStatus('Checking your private Tailscale connection...', False);
  WizardForm.Update;
  ExtractTemporaryFile('check-tailscale.ps1');
  CheckerPath := ExpandConstant('{tmp}\check-tailscale.ps1');

  if not Exec('powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -File "' + CheckerPath + '"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    SetStatus('PocketPC could not run the Tailscale check. Click Check again.', False);
    exit;
  end;

  case ResultCode of
    0:
      begin
        SetStatus('Ready - Tailscale is connected and your private address is available.', True);
        Result := True;
      end;
    10:
      SetStatus('Tailscale is not installed on this PC. Install it, sign in, then click Check again.', False);
    11:
      SetStatus('Tailscale is installed but not connected. Open Tailscale, sign in, then click Check again.', False);
    12:
      SetStatus('Tailscale is still preparing its private address. Wait a moment, then click Check again.', False);
  else
    SetStatus('Tailscale could not be verified. Open Tailscale, connect it, then click Check again.', False);
  end;
end;

procedure CheckButtonClick(Sender: TObject);
begin
  CheckTailscale;
end;

procedure DownloadButtonClick(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', 'https://tailscale.com/download/windows', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure InitializeWizard;
var
  Heading: TNewStaticText;
  Instructions: TNewStaticText;
  CheckButton: TNewButton;
  DownloadButton: TNewButton;
begin
  TailscalePage := CreateCustomPage(wpWelcome,
    'Connect PocketPC securely',
    'PocketPC uses your private Tailscale network. It is not exposed to the public internet.');

  Heading := TNewStaticText.Create(TailscalePage);
  Heading.Parent := TailscalePage.Surface;
  Heading.Left := 0;
  Heading.Top := 8;
  Heading.Width := TailscalePage.SurfaceWidth;
  Heading.Height := 28;
  Heading.Caption := 'Before installing PocketPC';
  Heading.Font.Style := [fsBold];
  Heading.Font.Size := 12;

  Instructions := TNewStaticText.Create(TailscalePage);
  Instructions.Parent := TailscalePage.Surface;
  Instructions.Left := 0;
  Instructions.Top := 48;
  Instructions.Width := TailscalePage.SurfaceWidth;
  Instructions.Height := 126;
  Instructions.AutoSize := False;
  Instructions.WordWrap := True;
  Instructions.Caption :=
    '1. Install Tailscale on this Windows PC and on your phone.' + #13#10 +
    '2. Sign in to the same Tailscale account on both devices.' + #13#10 +
    '3. Make sure Tailscale says Connected on this PC.' + #13#10 +
    '4. Click Check again below. Setup continues only after the private connection is ready.';

  TailscaleStatus := TNewStaticText.Create(TailscalePage);
  TailscaleStatus.Parent := TailscalePage.Surface;
  TailscaleStatus.Left := 0;
  TailscaleStatus.Top := 188;
  TailscaleStatus.Width := TailscalePage.SurfaceWidth;
  TailscaleStatus.Height := 48;
  TailscaleStatus.AutoSize := False;
  TailscaleStatus.WordWrap := True;
  TailscaleStatus.Font.Style := [fsBold];

  CheckButton := TNewButton.Create(TailscalePage);
  CheckButton.Parent := TailscalePage.Surface;
  CheckButton.Left := 0;
  CheckButton.Top := 250;
  CheckButton.Width := 120;
  CheckButton.Caption := 'Check again';
  CheckButton.OnClick := @CheckButtonClick;

  DownloadButton := TNewButton.Create(TailscalePage);
  DownloadButton.Parent := TailscalePage.Surface;
  DownloadButton.Left := 132;
  DownloadButton.Top := 250;
  DownloadButton.Width := 142;
  DownloadButton.Caption := 'Download Tailscale';
  DownloadButton.OnClick := @DownloadButtonClick;

  SetStatus('Setup will check Tailscale when you open this page.', False);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = TailscalePage.ID then
    CheckTailscale;

  if CurPageID = wpFinished then
  begin
    if ConfigurationSucceeded then
      WizardForm.FinishedLabel.Caption :=
        'PocketPC is installed and its private Tailscale address is ready.' + #13#10 + #13#10 +
        'Launch PocketPC to see your phone connection address, pairing code, and QR code.'
    else
      WizardForm.FinishedLabel.Caption :=
        'PocketPC was installed, but its private connection could not be configured.' + #13#10 + #13#10 +
        'Keep Tailscale connected and run PocketPC. If it reports a setup problem, run this installer again.';
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = TailscalePage.ID then
  begin
    if not CheckTailscale then
    begin
      MsgBox(
        'PocketPC needs an active Tailscale connection before installation.' + #13#10 + #13#10 +
        'Install or connect Tailscale on this PC, then click Check again.',
        mbInformation, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := 'Configuring PocketPC private networking...';
    WizardForm.Update;
    ConfigurationSucceeded := Exec('powershell.exe',
      '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\configure-installed.ps1') +
      '" -ExePath "' + ExpandConstant('{app}\PocketPC.exe') +
      '" -ConfigDirectory "' + ExpandConstant('{commonappdata}\PocketPC') + '"',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  end;
end;
