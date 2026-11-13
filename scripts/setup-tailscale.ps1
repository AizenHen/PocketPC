param(
    [ValidateRange(1024, 65535)]
    [int]$LocalPort = 8765
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Tailscale -PathType Leaf)) {
    throw 'Tailscale is not installed. Install it from https://tailscale.com/download/windows and sign in first.'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'PocketPC Python environment is missing. Complete the README installation first.'
}

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open PowerShell with Run as administrator, return to the PocketPC folder, and run this script again.'
}

$Status = (& $Tailscale status --json | ConvertFrom-Json)
if ($Status.BackendState -ne 'Running') {
    throw 'Tailscale is not connected. Open Tailscale, sign in, and connect before continuing.'
}
$TailIP = @($Status.Self.TailscaleIPs | Where-Object { $_ -match '^100\.' })[0]
$DnsName = ([string]$Status.Self.DNSName).TrimEnd('.')
if (-not $TailIP -or -not $DnsName.EndsWith('.ts.net')) {
    throw 'PocketPC needs a Tailscale IPv4 address and MagicDNS/HTTPS name. Enable MagicDNS and HTTPS in the Tailscale admin console.'
}

$SavedConfig = @{
    public_host = $DnsName.ToLowerInvariant()
    advertise_ip = $TailIP
} | ConvertTo-Json
$SavedConfig | Set-Content -LiteralPath (Join-Path $ProjectRoot 'pocketpc.local.json') -Encoding UTF8
$InstalledConfigDirectory = Join-Path $env:ProgramData 'PocketPC'
New-Item -ItemType Directory -Path $InstalledConfigDirectory -Force | Out-Null
$SavedConfig | Set-Content -LiteralPath (Join-Path $InstalledConfigDirectory 'config.json') -Encoding UTF8

# Serve is tailnet-only. This does not enable Tailscale Funnel.
& $Tailscale serve --bg "http://127.0.0.1:$LocalPort"
if ($LASTEXITCODE -ne 0) { throw 'Tailscale Serve setup failed.' }

# Loopback + Tailscale Serve needs no PocketPC-specific inbound exception.
Get-NetFirewallRule -Name 'PocketPC-HTTPS','PocketPC-WebRTC','PocketPC-Tailscale-STUN','PocketPC-LAN-STUN','PocketPC-LAN-WebRTC','PocketPC-LAN-mDNS' -ErrorAction SilentlyContinue | Remove-NetFirewallRule

Write-Host ''
Write-Host 'PocketPC is configured for private Tailscale access only.' -ForegroundColor Green
Write-Host "iPhone address: https://$DnsName"
Write-Host "Tailscale video address: $TailIP"
Write-Host 'No PocketPC-specific Windows Firewall rule is required. Tailscale Funnel was not enabled.'
