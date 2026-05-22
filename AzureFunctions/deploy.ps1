# Deploy Colectica MCP Server to Azure Functions
# Usage: ./deploy.ps1 [-Env dev] [-Location eastus]
param(
    [string]$Env      = "dev",
    [string]$Location = "eastus"
)

$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot

Write-Host "[INFO] Deploying colectica-mcp to Azure Functions (env=$Env, location=$Location)"

# Ensure azd is available
if (-not (Get-Command azd -ErrorAction SilentlyContinue)) {
    Write-Error "Azure Developer CLI (azd) not found. Install: winget install Microsoft.Azd"
}

# Set environment
$env:AZURE_ENV_NAME   = "colectica-mcp-$Env"
$env:AZURE_LOCATION   = $Location
$env:ENVIRONMENT      = $Env

Push-Location $ScriptDir
try {
    azd up --no-prompt
} finally {
    Pop-Location
}

Write-Host "[INFO] Deployment complete."
Write-Host "[INFO] MCP endpoint: https://colectica-mcp.azurewebsites.net/api/mcp"
