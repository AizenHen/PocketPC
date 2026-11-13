$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $PSScriptRoot 'launch-pocketpc.pyw'
$Pythonw = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
$Icon = Join-Path $ProjectRoot 'assets\pocketpc.ico'
if (-not (Test-Path -LiteralPath $Launcher -PathType Leaf)) { throw 'PocketPC launcher is missing.' }
if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) { throw 'PocketPC virtual environment is missing. Follow the installation steps in README.md.' }
if (-not (Test-Path -LiteralPath $Icon -PathType Leaf)) { throw 'PocketPC icon is missing. Reinstall the project requirements and run scripts\build-icon.py.' }

$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $Desktop 'PocketPC.lnk'
$TemporaryShortcut = Join-Path $ProjectRoot 'PocketPC.installing.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($TemporaryShortcut)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = "`"$Launcher`""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.IconLocation = "$Icon,0"
$Shortcut.Description = 'Open PocketPC private iPhone screen viewer'
$Shortcut.Save()
Move-Item -LiteralPath $TemporaryShortcut -Destination $ShortcutPath -Force
Write-Host "PocketPC desktop shortcut installed: $ShortcutPath"
