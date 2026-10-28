#define AppName "Frost Vision Studio"
#define AppVersion "0.2.0"
#define AppExe "FrostVisionStudio.exe"

[Setup]
AppId={{D499CC05-DC65-4E35-AF78-C57740A52147}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Ashraf Ali Hussain Al-Saloul
AppPublisherURL=https://github.com/ASHRAF-2004/frost-vision-studio
AppSupportURL=https://github.com/ASHRAF-2004/frost-vision-studio/issues
AppUpdatesURL=https://github.com/ASHRAF-2004/frost-vision-studio/releases
DefaultDirName={localappdata}\Programs\FrostVisionStudio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
LicenseFile=..\docs\TERMS.md
InfoAfterFile=..\docs\PRIVACY.md
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\dist
OutputBaseFilename=FrostVisionStudio-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\FrostVisionStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{autoprograms}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "FrostVisionStudio"; Flags: dontcreatekey uninsdeletevalue

; User settings and selected source media are deliberately preserved.
