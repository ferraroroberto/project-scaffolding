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
      4. pytest (non-e2e) — unit suite, tests/e2e excluded
      5. pytest (e2e)  — diff-proportionate: the browser slice is routed by
                         scripts/classify_e2e.py against the .fleet.toml [e2e]
                         rules (skip / static / full), fail-safe to full
                         (project-scaffolding#180). Auto-boots Streamlit per
                         its fixture.

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
    "src/notify/",
    "src/doc_capture/",
    "tests/e2e/_geometry.py",
    "scripts/classify_e2e.py"
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
Invoke-Stage "pytest (unit, non-e2e)"             { & $py -m pytest --ignore=tests/e2e }

# ---------------------------------------------------------------- e2e routing
# Diff-proportionate e2e routing (project-scaffolding#180). Instead of always
# running the whole tests/e2e suite, classify the branch's changed files vs
# main and run a browser slice proportionate to the diff: backend/docs-only ->
# skip the browser suite, static assets -> the narrow smoke target, real
# UI/behaviour -> the full suite. Fail-safe: a mixed/ambiguous/unrecognized
# diff (or no [e2e] table declared) runs the full suite. The path->tier rules
# live in .fleet.toml [e2e] (one auditable place); scripts/classify_e2e.py is
# the mechanism. On CI the full suite always runs -- the local gate is where
# routing is proven first.
$tier = "full"; $e2eTarget = "tests/e2e"; $e2eBrowsers = ""; $routeReason = ""
if ($env:CI -eq "true") {
    $routeReason = "CI always runs the full e2e suite"
} else {
    $classifyOut = & $py "scripts/classify_e2e.py"
    $kv = @{}
    foreach ($line in $classifyOut) {
        if ($line -match '^(E2E_[A-Z_]+)=(.*)$') { $kv[$matches[1]] = $matches[2] }
    }
    if ($kv.ContainsKey("E2E_TIER") -and $kv["E2E_TIER"]) {
        $tier = $kv["E2E_TIER"]
        $e2eTarget = $kv["E2E_PYTEST_TARGET"]
        $e2eBrowsers = $kv["E2E_BROWSERS"]
        $routeReason = $kv["E2E_REASON"]
    } else {
        $routeReason = "classifier gave no verdict -- defaulting to full (fail-safe)"
    }
}

if ($tier -eq "skip") {
    Write-Host ""
    Write-Host ">> e2e routing: SKIP browser suite (no e2e surface touched)" -ForegroundColor Cyan
    Write-Host "   reason: $routeReason" -ForegroundColor DarkGray
    Write-Host "[PASS] pytest (e2e) - skipped, diff touches no e2e surface" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host ">> e2e routing: $tier" -ForegroundColor Cyan
    Write-Host "   reason: $routeReason" -ForegroundColor DarkGray
    $e2eArgs = @($e2eTarget)
    foreach ($b in ($e2eBrowsers -split ',' | Where-Object { $_ })) {
        $e2eArgs += @("--browser", $b)
    }
    $label = if ($e2eBrowsers) { $e2eBrowsers } else { "suite-default" }
    Invoke-Stage "pytest e2e (${tier}: $e2eTarget, $label)" { & $py -m pytest @e2eArgs }
}

Write-Host ""
Write-Host "[PASS] all checks green - safe to ship." -ForegroundColor Green
