#Requires -Version 5.1
<#
.SYNOPSIS
    Pre-ship verification gate for project-scaffolding. One pass/fail pipeline.

.DESCRIPTION
    Runs, fail-fast, the checks every consumer enforces — so a vendor-verbatim
    primitive (e.g. app/tray/single_instance.py) can never ship lint- or
    type-dirty and turn the CI of every repo that copies it red.

    Stages:
      1. byte-compile  — every .py under app/ src/ tests/ parses
      2. ruff          — lint the whole repo (ruff defaults + pyupgrade)
      3. static ratchet — scripts/static_ratchet.py: fails only on a duplicate
                         block (jscpd, Python + JS) or unused import/variable
                         (ruff F401/F841) NEW relative to the committed baseline;
                         opt-in via .fleet.toml [static_ratchet]; exit 3 =
                         "not confirmed" (Node/ruff unusable), a failure, never
                         a pass (project-scaffolding#410, docs/static-ratchet.md)
      4. comment ratchet — scripts/comment_ratchet.py: fails only when a file's
                         count of #NNN issue references inside comments (py, js,
                         css, ps1) rises above the committed baseline; opt-in via
                         .fleet.toml [comment_ratchet]; exit 3 = "not confirmed"
                         (git/scanner unusable), a failure, never a pass
                         (docs/comment-ratchet.md)
      5. docs ratchet  — scripts/docs_ratchet.py: fails only when the root
                         README passes its byte budget or a file's count of
                         history markers (issue references, dated and changelog
                         headings) in README.md / docs/**/*.md rises above the
                         committed baseline; opt-in via .fleet.toml
                         [docs_ratchet]; exit 3 = "not confirmed", a failure,
                         never a pass (docs/docs-ratchet.md)
      6. structure ratchet — scripts/structure_ratchet.py: fails when a file
                         passes 1,000 lines, a Python/JS function 100 lines, a
                         directory 40 modules, or a src/ module imports app/,
                         beyond the committed baseline, or a root folder falls
                         outside the declared shape; opt-in via .fleet.toml
                         [structure_ratchet]; exit 3 = "not confirmed", a
                         failure, never a pass (docs/structure-ratchet.md)
      7. instruction ratchet — scripts/instruction_ratchet.py: fails when an
                         instruction file (CLAUDE.md, AGENTS.md, rules, SKILL.md,
                         a skill's reference docs) gains a hit of a deterministic
                         prompt-audit lint rule, or passes its size cap, beyond
                         the committed baseline; opt-in via .fleet.toml
                         [instruction_ratchet]; exit 3 = "not confirmed", a
                         failure, never a pass (docs/instruction-ratchet.md)
      8. mypy --strict — the vendor-verbatim primitives only; the list is
                         derived from .fleet.toml's [components] catalog via
                         scripts/vendored_catalog.py, never hand-maintained here
      9. pytest (non-e2e) — unit suite, tests/e2e excluded
     10. pytest (e2e)  — diff-proportionate: the browser slice is routed by
                         scripts/classify_e2e.py against the .fleet.toml [e2e]
                         rules (skip / static / full), fail-safe to full
                         (project-scaffolding#180). Auto-boots Streamlit per
                         its fixture.
     11. shot baseline — scripts/shot_baseline.py: compares the screenshots the
                         e2e slice recaptured (phone + desktop, light + dark)
                         with the committed baseline, fails on a visible change,
                         restores the tree; runs the capture itself when the
                         slice did not; skipped with the browser suite; exit 3 =
                         "not confirmed", a failure, never a pass
                         (docs/playwright-ui-testing.md "Screenshot baseline")

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
# ships. The list is NOT maintained here: it is derived from .fleet.toml's
# [components] catalog, the one canonical answer to "what does this scaffold
# publish" (#230). A second hand-kept list is how a component ends up gated in
# one place and invisible in another — add the component to [components] and it
# is gated, catalogued and drift-checked from that single declaration.
$catalogLines = & $py "scripts/vendored_catalog.py" "mypy-targets"
$catalogExit = $LASTEXITCODE
$VendoredModules = @($catalogLines | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($catalogExit -ne 0 -or $VendoredModules.Count -eq 0) {
    Write-Host "[FAIL] could not derive the vendored-module list from .fleet.toml [components]" -ForegroundColor Red
    Write-Host "       (an empty list would pass 'mypy --strict' while checking nothing)" -ForegroundColor Red
    Write-Host "       Run: $py scripts/vendored_catalog.py mypy-targets" -ForegroundColor Red
    exit 1
}
Write-Host "vendored components (mypy --strict): $($VendoredModules.Count) targets from .fleet.toml [components]" -ForegroundColor DarkGray

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
Invoke-Stage "static ratchet"                     { & $py "scripts/static_ratchet.py" }
Invoke-Stage "comment ratchet"                    { & $py "scripts/comment_ratchet.py" }
Invoke-Stage "docs ratchet"                       { & $py "scripts/docs_ratchet.py" }
Invoke-Stage "structure ratchet"                  { & $py "scripts/structure_ratchet.py" }
Invoke-Stage "instruction ratchet"                { & $py "scripts/instruction_ratchet.py" }
Invoke-Stage "mypy --strict (vendored)"           { & $py -m mypy @VendoredModules }
Invoke-Stage "pytest (unit, non-e2e)"             { & $py -m pytest --ignore=tests/e2e }

# ---------------------------------------------------------------- e2e routing
# Diff-proportionate e2e routing (project-scaffolding#180). Instead of always
# running the whole tests/e2e suite, classify the branch's changed files vs
# main and run a browser slice proportionate to the diff: backend/docs-only ->
# skip the browser suite, static assets -> the narrow smoke target, real
# UI/behaviour -> the full suite, or only its declared surface's targets when
# every full-tier path sits in one [[e2e.surface]] (#258). Fail-safe: a
# mixed/ambiguous/unrecognized diff (or no [e2e] table declared) runs the full
# suite. The path->tier rules
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
    # A `surface` tier (#258) names several targets, space-separated -- split
    # them into separate pytest args (one arg "a.py b.py" is a missing path).
    $e2eArgs = @($e2eTarget -split '\s+' | Where-Object { $_ })
    foreach ($b in ($e2eBrowsers -split ',' | Where-Object { $_ })) {
        $e2eArgs += @("--browser", $b)
    }
    $label = if ($e2eBrowsers) { $e2eBrowsers } else { "suite-default" }
    # Taken before the run: a shot written after it was recaptured by it.
    $shotSince = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
    Invoke-Stage "pytest e2e (${tier}: $e2eTarget, $label)" { & $py -m pytest @e2eArgs }

    # Screenshot baseline: when the slice just ran the capture, compare what it
    # wrote; otherwise run the capture itself. Either way the tree is restored.
    $sliceCaptured = ($e2eArgs -contains "tests/e2e") -or (@($e2eArgs | Where-Object { $_ -like "tests/e2e/test_shot_baseline.py*" }).Count -gt 0)
    if ($sliceCaptured) {
        $since = $shotSince.ToString([Globalization.CultureInfo]::InvariantCulture)
        Invoke-Stage "shot baseline (compare)" { & $py "scripts/shot_baseline.py" --check-tree --since $since }
    } else {
        Invoke-Stage "shot baseline (capture + compare)" { & $py "scripts/shot_baseline.py" --baseline }
    }
}
if ($tier -eq "skip") {
    Write-Host "[SKIP] shot baseline - no e2e surface touched, so no screen was recaptured or compared" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "[PASS] all checks green - safe to ship." -ForegroundColor Green
