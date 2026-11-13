param(
    [ValidateRange(1024, 65535)]
    [int]$LocalPort = 8765
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Python environment is missing. Follow README.md installation first.' }
if (-not (Test-Path -LiteralPath $Tailscale -PathType Leaf)) { throw 'Tailscale is not installed.' }

$Status = (& $Tailscale status --json | ConvertFrom-Json)
if ($Status.BackendState -ne 'Running') { throw 'Tailscale is not connected.' }
$TailIP = @($Status.Self.TailscaleIPs | Where-Object { $_ -match '^100\.' })[0]
$DnsName = ([string]$Status.Self.DNSName).TrimEnd('.')
if (-not $TailIP -or -not $DnsName.EndsWith('.ts.net')) { throw 'Tailscale MagicDNS/HTTPS is not ready. Run setup-tailscale.ps1.' }

Push-Location $ProjectRoot
try {
    & $Python -m backend.main --public-host $DnsName --advertise-ip $TailIP --port $LocalPort --stun-port 3478
} finally {
    Pop-Location
}
