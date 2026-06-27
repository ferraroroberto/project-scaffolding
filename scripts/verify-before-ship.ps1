#Requires -Version 5.1
<#
.SYNOPSIS
    Pre-ship verification gate for project-scaffolding. One pass/fail pipeline.

.DESCRIPTION
    Runs, fail-fast, the checks every consumer enforces — so a vendor-verbatim
    primitive (e.g. app/tray/single_instance.py) can never ship lint- or
    type-dirty and turn the CI of every repo that copies it red (the exact
    avoidable round-trips behind project-scaffolding#48/#49/#50).

    Stages:
      1. byte-compile  — every .py under app/ src/ tests/ parses
      2. ruff          — lint the whole repo (ruff defaults + pyupgrade)
      3. mypy --strict — the vendor-verbatim primitives only ($VendoredModules)
      4. pytest        — unit + headless e2e (auto-boots Streamlit per its fixture)

    Strictness lives in pyproject.toml ([tool.ruff.lint], [tool.mypy]); this
    script only sequences the tools. Anchors to the repo root, so run it from
    anywhere:  & .\scripts\verify-before-ship.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "[FAIL] .venv not found at $py" -ForegroundColor Red
    Write-Host "       Create it and run: $py -m pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}

# Vendor-verbatim primitives — copied byte-identical into consumer repos. Each
# is gated with mypy --strict here so it passes what consumers enforce BEFORE it
# ships. Append the next module to this list when a new vendored primitive lands.
$VendoredModules = @(
    "app/tray/single_instance.py",
    "src/notify/"
)

function Invoke-Stage {
    param([string]$Name, [scriptblock]$Body)
    Write-Host ""
    Write-Host ">> $Name" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] $Name (exit $LASTEXITCODE)" -ForegroundColor Red
        exit 1
    }
    Write-Host "[PASS] $Name" -ForegroundColor Green
}

Invoke-Stage "byte-compile"                       { & $py -m compileall -q app src tests }
Invoke-Stage "ruff"                               { & $py -m ruff check . }
Invoke-Stage "mypy --strict (vendored)"           { & $py -m mypy @VendoredModules }
Invoke-Stage "pytest (unit + e2e)"                { & $py -m pytest }

Write-Host ""
Write-Host "[PASS] all checks green - safe to ship." -ForegroundColor Green
