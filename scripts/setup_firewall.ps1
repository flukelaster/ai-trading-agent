# setup_firewall.ps1 — Configure Windows Firewall to restrict MT5 Bridge access
# Run as Administrator on Contabo VPS
#
# Usage: .\setup_firewall.ps1 -BackendIP "YOUR_BACKEND_IP"
# Example: .\setup_firewall.ps1 -BackendIP "203.0.113.50"

param(
    [Parameter(Mandatory=$true)]
    [string]$BackendIP
)

$Port = 8001
$RuleName = "MT5Bridge-Allow-Backend"
$BlockRuleName = "MT5Bridge-Block-All"

Write-Host "Configuring firewall for MT5 Bridge (port $Port)..."
Write-Host "Allowing access from: $BackendIP"

# Remove existing rules if they exist
$existingRules = Get-NetFirewallRule -DisplayName "$RuleName*" -ErrorAction SilentlyContinue
if ($existingRules) {
    $existingRules | Remove-NetFirewallRule
    Write-Host "Removed existing allow rules"
}

$existingBlock = Get-NetFirewallRule -DisplayName $BlockRuleName -ErrorAction SilentlyContinue
if ($existingBlock) {
    $existingBlock | Remove-NetFirewallRule
    Write-Host "Removed existing block rule"
}

# Step 1: Block ALL inbound traffic on port 8001
New-NetFirewallRule `
    -DisplayName $BlockRuleName `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $Port `
    -Action Block `
    -Profile Any `
    -Description "Block all inbound access to MT5 Bridge"

Write-Host "Created block rule for port $Port"

# Step 2: Allow from backend IP (higher priority)
New-NetFirewallRule `
    -DisplayName "$RuleName-$BackendIP" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $Port `
    -RemoteAddress $BackendIP `
    -Action Allow `
    -Profile Any `
    -Description "Allow MT5 Bridge access from backend ($BackendIP)"

Write-Host "Created allow rule for $BackendIP"

# Step 3: Allow localhost (for local watchdog health checks)
New-NetFirewallRule `
    -DisplayName "$RuleName-Localhost" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $Port `
    -RemoteAddress "127.0.0.1" `
    -Action Allow `
    -Profile Any `
    -Description "Allow MT5 Bridge access from localhost"

Write-Host "Created allow rule for localhost"

Write-Host ""
Write-Host "Firewall configured:"
Write-Host "  - Port $Port BLOCKED for all IPs"
Write-Host "  - ALLOWED: $BackendIP (backend)"
Write-Host "  - ALLOWED: 127.0.0.1 (localhost/watchdog)"
Write-Host ""
Write-Host "To verify: Get-NetFirewallRule -DisplayName 'MT5Bridge*' | Format-Table"
