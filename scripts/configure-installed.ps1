param(
    [Parameter(Mandatory = $true)]
    [string]$ExePath,
    [Parameter(Mandatory = $true)]
    [string]$ConfigDirectory
)

$ErrorActionPreference = 'Stop'
$Tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) { throw 'PocketPC.exe was not installed.' }
if (-not (Test-Path -LiteralPath $Tailscale -PathType Leaf)) { throw 'Install and connect Tailscale before installing PocketPC.' }

$Status = (& $Tailscale status --json | ConvertFrom-Json)
if ($Status.BackendState -ne 'Running') { throw 'Connect Tailscale before installing PocketPC.' }
$TailIP = @($Status.Self.TailscaleIPs | Where-Object { $_ -match '^100\.' })[0]
$DnsName = ([string]$Status.Self.DNSName).TrimEnd('.').ToLowerInvariant()
if (-not $TailIP -or -not $DnsName.EndsWith('.ts.net')) { throw 'Tailscale MagicDNS/HTTPS is not ready.' }

& $Tailscale serve --bg 'http://127.0.0.1:8765'
if ($LASTEXITCODE -ne 0) { throw 'Tailscale Serve setup failed.' }

New-Item -ItemType Directory -Path $ConfigDirectory -Force | Out-Null
@{ public_host = $DnsName; advertise_ip = $TailIP } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ConfigDirectory 'config.json') -Encoding UTF8

Get-NetFirewallRule -Name 'PocketPC-Installed-STUN','PocketPC-Installed-WebRTC' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name 'PocketPC-Installed-STUN' -DisplayName 'PocketPC private STUN' `
    -Direction Inbound -Action Allow -Program $ExePath -Protocol UDP -LocalPort 3478 `
    -LocalAddress $TailIP -RemoteAddress '100.64.0.0/10' -Profile Any | Out-Null
New-NetFirewallRule -Name 'PocketPC-Installed-WebRTC' -DisplayName 'PocketPC encrypted private video' `
    -Direction Inbound -Action Allow -Program $ExePath -Protocol UDP -LocalPort Any `
    -LocalAddress $TailIP -RemoteAddress '100.64.0.0/10' -Profile Any | Out-Null
