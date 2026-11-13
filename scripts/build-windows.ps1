$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Create the PocketPC virtual environment first.' }

& $Python (Join-Path $ProjectRoot 'scripts\build-icon.py')
if ($LASTEXITCODE -ne 0) { throw 'PocketPC icon build failed.' }

Push-Location (Join-Path $ProjectRoot 'frontend')
try { npm run build } finally { Pop-Location }

& $Python -m PyInstaller --noconfirm --clean --log-level WARN (Join-Path $ProjectRoot 'PocketPC.spec')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }

$InputIcon = Join-Path $ProjectRoot 'assets\pocketpc.ico'
$InputEntry = Join-Path $ProjectRoot 'pocketpc_input_helper.py'
& $Python -m PyInstaller --noconfirm --clean --log-level WARN --onefile --windowed `
    --name PocketPCInput --specpath (Join-Path $ProjectRoot 'build') --icon $InputIcon $InputEntry
if ($LASTEXITCODE -ne 0) { throw 'Elevated input helper build failed.' }

$InnoRegistry = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1' -ErrorAction SilentlyContinue
$Iscc = @(
    $(if ($InnoRegistry.InstallLocation) { Join-Path $InnoRegistry.InstallLocation 'ISCC.exe' }),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $Iscc) { throw 'Install Inno Setup 6, then rerun this script to create the installer.' }
& $Iscc /Qp (Join-Path $ProjectRoot 'installer\PocketPC.iss')
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup build failed.' }
Write-Host "PocketPC installer: $ProjectRoot\release\PocketPC-Setup-1.7.0.exe" -ForegroundColor Green
