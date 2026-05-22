param([int]$Port = 7071)

$ErrorActionPreference = "Stop"
$baseUrl = "http://localhost:$Port"

# Load env
$envFile = Join-Path (Join-Path $PSScriptRoot "..") ".env"
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^([^#][^=]+)=(.+)$') {
        [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), "Process")
    }
}
$env:COLECTICA_MCP_TRANSPORT = "streamable-http"

# Start func as background job
$appDir = Join-Path (Join-Path $PSScriptRoot "..") "hosting"
$appDir = Join-Path $appDir "app"
$appDir = (Resolve-Path $appDir).Path
Write-Host "Starting func from: $appDir"

$job = Start-Job -ScriptBlock {
    param($dir, $port, $baseUrl, $bearerToken)
    Set-Location $dir
    $env:COLECTICA_BASE_URL = $baseUrl
    $env:COLECTICA_BEARER_TOKEN = $bearerToken
    $env:COLECTICA_MCP_TRANSPORT = "streamable-http"
    func start --port $port 2>&1
} -ArgumentList $appDir, $Port, $env:COLECTICA_BASE_URL, $env:COLECTICA_BEARER_TOKEN

Write-Host "Job ID: $($job.Id) — waiting for port $Port..."

# Wait up to 30s for the port
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $tcp = [System.Net.Sockets.TcpClient]::new("127.0.0.1", $Port)
        $tcp.Close()
        $ready = $true
        break
    } catch { }
}

if (-not $ready) {
    Write-Host "Port $Port never opened. Job output:"
    Receive-Job $job
    Stop-Job $job; Remove-Job $job
    exit 1
}

Write-Host "Port $Port is OPEN — running tests..."

# Get function key
$keys = Invoke-RestMethod "$baseUrl/admin/host/keys" -TimeoutSec 5
$key = $keys.keys[0].value
$h = @{ "x-functions-key" = $key }

# 1. Health
Write-Host "`n=== HEALTH CHECK ==="
$health = Invoke-RestMethod "$baseUrl/api/health" -Headers $h -TimeoutSec 10
Write-Host ($health | ConvertTo-Json)

# 2. MCP initialize — FastMCP requires both accept types per MCP spec
Write-Host "`n=== MCP initialize ==="
$mcpInit = @{
    jsonrpc = "2.0"; id = 1; method = "initialize"
    params  = @{
        protocolVersion = "2024-11-05"
        capabilities    = @{}
        clientInfo      = @{ name = "test"; version = "0" }
    }
} | ConvertTo-Json -Depth 5

try {
    $initH = $h.Clone()
    $initH["Content-Type"] = "application/json"
    $initH["Accept"] = "application/json, text/event-stream"
    $resp = Invoke-WebRequest "$baseUrl/api/mcp" -Method POST -Headers $initH -Body $mcpInit -TimeoutSec 15
    Write-Host "Status: $($resp.StatusCode)"
    $preview = $resp.Content.Substring(0, [Math]::Min(600, $resp.Content.Length))
    Write-Host "Body preview: $preview"
} catch {
    Write-Host "Error: $($_.Exception.Message)"
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = [System.IO.StreamReader]::new($stream)
        Write-Host "Response body: $($reader.ReadToEnd())"
    }
}

# Cleanup
Write-Host "`n=== Stopping func ==="
Stop-Job $job
Write-Host "Last job output:"
Receive-Job $job | Select-Object -Last 20
Remove-Job $job
