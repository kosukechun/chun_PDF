[Setup]
AppId=chunPDF
AppName=chun PDF
AppVersion=0.1.0
DefaultDirName={localappdata}\Programs\chun PDF
DefaultGroupName=chun PDF
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=build\installer
OutputBaseFilename=chunPDF-Setup-x64
Compression=lzma2
SolidCompression=yes
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\chunPDF.exe
WizardStyle=modern
AppMutex=Local\chunPDF.MainWindow

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作成"; Flags: unchecked
Name: "startup"; Description: "Windowsへのサインイン時に通知領域で起動"; Flags: unchecked

[Files]
Source: "dist\chunPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\chun PDF"; Filename: "{app}\chunPDF.exe"
Name: "{userdesktop}\chun PDF"; Filename: "{app}\chunPDF.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "chunPDF"; ValueData: """{app}\chunPDF.exe"" --tray"; Tasks: startup; Flags: uninsdeletevalue

[UninstallDelete]
Type: files; Name: "{userappdata}\chunPDF\settings.json"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'chunPDF');
end;

