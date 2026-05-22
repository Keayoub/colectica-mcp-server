# SPDX-License-Identifier: Apache-2.0
# Build and publish colectica-mcp-server to PyPI
# Usage:
#   ./build_pypi.ps1                         # build only
#   ./build_pypi.ps1 -Publish                # build + upload to PyPI
#   ./build_pypi.ps1 -TestPyPI               # build + upload to TestPyPI
#   ./build_pypi.ps1 -SkipInstallTest        # skip post-build smoke test

param(
    [switch]$Publish,
    [switch]$TestPyPI,
    [switch]$SkipInstallTest
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot

Set-Location $RepoRoot

# ── Read version from __version__.py ─────────────────────────────────────────
Write-Host "Reading version..." -ForegroundColor Cyan
$version = & python -c "import sys; sys.path.insert(0, 'src'); from colectica_mcp.__version__ import __version__; print(__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Could not read version from src/colectica_mcp/__version__.py" -ForegroundColor Red
    exit 1
}
Write-Host "Version: $version" -ForegroundColor Green

# ── Clean previous artifacts ──────────────────────────────────────────────────
Write-Host "`nCleaning build artifacts..." -ForegroundColor Cyan
$dirsToClean = @(
    "build",
    "dist",
    "src\colectica_mcp_server.egg-info",
    "colectica_mcp_server.egg-info"
)
foreach ($dir in $dirsToClean) {
    $full = Join-Path $RepoRoot $dir
    if (Test-Path $full) {
        Remove-Item -Recurse -Force $full
        Write-Host "  Removed: $dir" -ForegroundColor Gray
    }
}

# ── Build ─────────────────────────────────────────────────────────────────────
Write-Host "`nBuilding package with uv..." -ForegroundColor Cyan
uv build
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: uv build failed." -ForegroundColor Red
    exit 1
}
Write-Host "Build complete." -ForegroundColor Green

# ── Verify dist artifacts ─────────────────────────────────────────────────────
$distFiles = Get-ChildItem -Path (Join-Path $RepoRoot "dist") -ErrorAction SilentlyContinue
if (-not $distFiles) {
    Write-Host "ERROR: No artifacts found in dist/" -ForegroundColor Red
    exit 1
}
Write-Host "`nArtifacts:" -ForegroundColor Cyan
$distFiles | ForEach-Object { Write-Host "  $($_.Name)" -ForegroundColor Gray }

# ── Smoke test: install from wheel and import ─────────────────────────────────
if (-not $SkipInstallTest) {
    Write-Host "`nRunning import smoke test..." -ForegroundColor Cyan
    $wheel = $distFiles | Where-Object { $_.Name -like "*.whl" } | Select-Object -First 1
    if ($wheel) {
        uv pip install --quiet "$($wheel.FullName)" 2>&1 | Out-Null
        $testResult = & python -c "from colectica_mcp.server import mcp; print('mcp object:', type(mcp).__name__)" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  $testResult" -ForegroundColor Green
            Write-Host "  Import test passed." -ForegroundColor Green
        } else {
            Write-Host "  Import test FAILED: $testResult" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "  No wheel found — skipping import test." -ForegroundColor Yellow
    }
}

# ── Publish ───────────────────────────────────────────────────────────────────
if ($Publish) {
    Write-Host "`nPublishing to PyPI..." -ForegroundColor Cyan
    uv publish
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Publish to PyPI failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "Published colectica-mcp-server $version to PyPI." -ForegroundColor Green
    Write-Host "  https://pypi.org/project/colectica-mcp-server/$version/" -ForegroundColor Gray
} elseif ($TestPyPI) {
    Write-Host "`nPublishing to TestPyPI..." -ForegroundColor Cyan
    uv publish --publish-url https://test.pypi.org/legacy/
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Publish to TestPyPI failed." -ForegroundColor Red
        exit 1
    }
    Write-Host "Published colectica-mcp-server $version to TestPyPI." -ForegroundColor Green
    Write-Host "  https://test.pypi.org/project/colectica-mcp-server/$version/" -ForegroundColor Gray
} else {
    Write-Host "`nBuild complete. Use -Publish to upload to PyPI, -TestPyPI for test index." -ForegroundColor Cyan
}
