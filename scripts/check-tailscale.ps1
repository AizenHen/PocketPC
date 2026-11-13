$ErrorActionPreference = 'Stop'

$Tailscale = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'

if (-not (Test-Path -LiteralPath $Tailscale -PathType Leaf)) {
    Write-Host 'Tailscale is not installed.'
    exit 10
}

try {
    $Status = & $Tailscale status --json | ConvertFrom-Json
} catch {
    Write-Host 'PocketPC could not read the Tailscale status.'
    exit 11
}

if ($Status.BackendState -ne 'Running') {
    Write-Host 'Tailscale is installed, but it is not connected.'
    exit 11
}

$TailIP = @($Status.Self.TailscaleIPs | Where-Object { $_ -match '^100\.' })[0]
$DnsName = ([string]$Status.Self.DNSName).TrimEnd('.').ToLowerInvariant()

if (-not $TailIP -or -not $DnsName.EndsWith('.ts.net')) {
    Write-Host 'Tailscale is connected, but its private IP or MagicDNS name is not ready.'
    exit 12
}

Write-Host "Tailscale is ready: $DnsName ($TailIP)"
exit 0
