[Setup]
AppId={{B58F5C55-112C-4260-9D50-57F85BA7D448}
AppName=AZURAI
AppVersion=1.0.0
DefaultDirName={localappdata}\Programs\AZURAI
DefaultGroupName=AZURAI
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AZURAI-Setup-{#Flavor}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\AZURAI.exe
LicenseFile=..\LICENSE
[Files]
Source: "..\dist\AZURAI\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\AZURAI"; Filename: "{app}\AZURAI.exe"
Name: "{group}\Thiết lập AZURAI"; Filename: "{app}\AZURAI.exe"; Parameters: "--configure"
Name: "{autodesktop}\AZURAI"; Filename: "{app}\AZURAI.exe"
[Run]
Filename: "{app}\AZURAI.exe"; Description: "Mở AZURAI"; Flags: nowait postinstall skipifsilent
