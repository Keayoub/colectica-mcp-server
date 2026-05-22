# SPDX-License-Identifier: Apache-2.0
# Diagnostics script for Colectica MCP Server
# Usage: pwsh -NoProfile -File ./diagnose.ps1

$ErrorActionPreference = "Continue"
$RepoRoot = $PSScriptRoot

$passed  = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()
$errors  = [System.Collections.Generic.List[string]]::new()

function Pass([string]$msg)  { $passed.Add("  $msg") }
function Warn([string]$msg)  { $warnings.Add("  $msg") }
function Fail([string]$msg)  { $errors.Add("  $msg") }

# ── 1. Server entry-point file ───────────────────────────────────────────────
$serverFile = Join-Path $RepoRoot "src\colectica_mcp\server.py"
if (Test-Path $serverFile) {
    Pass "src/colectica_mcp/server.py exists"
} else {
    Fail "src/colectica_mcp/server.py not found"
}

# ── 2. Python version ≥ 3.10 ────────────────────────────────────────────────
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) {
    Fail "python not found on PATH"
} else {
    $pyVersion = & python --version 2>&1
    if ($pyVersion -match "Python (\d+)\.(\d+)") {
        $major = [int]$Matches[1]; $minor = [int]$Matches[2]
        if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
            Pass "Python $major.$minor (>= 3.10)"
        } else {
            Fail "Python $major.$minor found — requires >= 3.10"
        }
    } else {
        Fail "Could not parse Python version: $pyVersion"
    }
}

# ── 3–5. Required packages ───────────────────────────────────────────────────
$packages = @(
    @{ Module = "mcp";    Label = "mcp" },
    @{ Module = "httpx";  Label = "httpx" },
    @{ Module = "dotenv"; Label = "python-dotenv" }
)
foreach ($pkg in $packages) {
    $result = & python -c "import $($pkg.Module)" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Pass "$($pkg.Label) is installed"
    } else {
        Fail "$($pkg.Label) is NOT installed — run: uv pip install $($pkg.Label)"
    }
}

# ── 6. COLECTICA_BASE_URL env var ────────────────────────────────────────────
$baseUrl = $env:COLECTICA_BASE_URL
if ($baseUrl) {
    Pass "COLECTICA_BASE_URL is set ($baseUrl)"
} else {
    Fail "COLECTICA_BASE_URL is not set — this is required"
}

# ── 7. Authentication credential ─────────────────────────────────────────────
$hasBearer = -not [string]::IsNullOrWhiteSpace($env:COLECTICA_BEARER_TOKEN)
$hasUser   = -not [string]::IsNullOrWhiteSpace($env:COLECTICA_USERNAME)
if ($hasBearer) {
    Pass "COLECTICA_BEARER_TOKEN is set"
} elseif ($hasUser) {
    Pass "COLECTICA_USERNAME is set (basic auth)"
} else {
    Warn "Neither COLECTICA_BEARER_TOKEN nor COLECTICA_USERNAME is set — unauthenticated requests may fail"
}

# ── 8. .env file ─────────────────────────────────────────────────────────────
$envFile = Join-Path $RepoRoot ".env"
if (Test-Path $envFile) {
    Pass ".env file exists in repo root"
} else {
    Warn ".env file not found — copy .env.example and fill in values"
}

# ── 9. requirements.txt ───────────────────────────────────────────────────────
$reqFile = Join-Path $RepoRoot "requirements.txt"
if (Test-Path $reqFile) {
    Pass "requirements.txt exists"
} else {
    Warn "requirements.txt not found — consider adding one for deployment"
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
if ($passed.Count -gt 0) {
    Write-Host "✅ Passed ($($passed.Count)):" -ForegroundColor Green
    $passed | ForEach-Object { Write-Host $_ -ForegroundColor Green }
}
if ($warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "⚠️  Warnings ($($warnings.Count)):" -ForegroundColor Yellow
    $warnings | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
}
if ($errors.Count -gt 0) {
    Write-Host ""
    Write-Host "❌ Errors ($($errors.Count)):" -ForegroundColor Red
    $errors | ForEach-Object { Write-Host $_ -ForegroundColor Red }
}

Write-Host ""
if ($errors.Count -eq 0 -and $warnings.Count -eq 0) {
    Write-Host "All checks passed — Colectica MCP Server is ready." -ForegroundColor Green
} elseif ($errors.Count -eq 0) {
    Write-Host "Passed with $($warnings.Count) warning(s) — review above." -ForegroundColor Yellow
} else {
    Write-Host "$($errors.Count) error(s) must be resolved before running the server." -ForegroundColor Red
    exit 1
}
