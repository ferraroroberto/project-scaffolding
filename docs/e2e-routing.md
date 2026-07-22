# Diff-proportionate e2e routing

The pre-ship gate (`scripts/verify-before-ship.ps1`) used to run the whole `tests/e2e` browser suite on every change, regardless of what the diff touched. For a dual-projection Playwright suite that is minutes of Chromium + WebKit for a diff that changed one backend function or one SVG — pure cost, no added signal.

**Diff-proportionate routing** fixes that: the gate's browser phase classifies the branch's changed files against a per-project rule table and runs a browser slice *proportionate* to the diff. It is **fail-safe** — any uncertainty escalates to the full suite, never narrows it — and **automatic**, driven by `git diff`, with no manual `--fast` flag.

This was proven first in `app-launcher` (its `scripts/classify_e2e.py`, issue #568 / PR #574) and promoted here as a parameterized fleet convention (`project-scaffolding#180`). The difference: app-launcher hardcoded *its* layout into the classifier; the scaffold version reads the rules from each repo's own `.fleet.toml`, so the **mechanism** is shared and the **rules** are declared per-project.

## Who this applies to

Only web-app-shaped repos with a real browser e2e suite benefit — the dual-projection Playwright apps (grocery, whatsapp-radar, family-accounting, mathgamesforkids, life-os, website, home-automation) and this scaffold itself. A pipeline repo with no `tests/e2e/` has nothing to route; it simply declares no `[e2e]` table and the gate keeps running whatever `pytest` it already runs.

## The three tiers

The gate's browser phase runs one of three tiers, chosen by the **worst** (highest) tier any changed file maps to:

| Tier | When | What runs |
|---|---|---|
| `skip` | every changed path matched a declared `none` rule (backend / docs / tooling only) | no browser suite at all |
| `static` | the worst-matching path is a `static` rule (inert assets — images, fonts, an inert vendored HTML fragment) | the narrow `static_pytest_target` (e.g. the smoke test), on `static_browsers` |
| `full` | any path matched a `full` rule, **or matched no rule at all**, **or** the diff is empty, **or** the repo declares no usable `[e2e]` table | the whole `full_pytest_target` (default `tests/e2e`) |

The `full` row is the fail-safe. **Under-testing must never be the outcome of uncertainty** — an unrecognized path, a mixed diff, a malformed table, or an empty diff all run the full suite. The table only ever narrows what an *already-recognized-as-narrow* diff runs; it can never make an unmatched change run less.

## Declaring the rules — the `.fleet.toml` `[e2e]` table

The rules live in each repo's `.fleet.toml` (the same file that already carries the fleet-map card), under an `[e2e]` table plus an ordered list of `[[e2e.rule]]` entries. TOML was chosen over a CLAUDE.md block so the classifier loads it with stdlib `tomllib` — zero custom parsing — and the rules are versioned alongside the code they classify.

```toml
[e2e]
static_pytest_target = "tests/e2e/test_smoke.py"  # what `static` runs
static_browsers       = ["chromium"]              # browsers for the static slice
full_pytest_target    = "tests/e2e"               # what `full` runs (the default)

# Rules are evaluated top-to-bottom; FIRST MATCH WINS. Put the most specific
# rules first (e.g. an inert-HTML STATIC rule above the FULL rule for the same
# directory).

# A rule matches on any combination of:
#   prefix      = "app/webapp/static/"   posix path prefix
#   extensions  = ["svg", "png"]         lowercase extensions (no dot)
#   path        = "app/app.py"           exact repo-relative path
#   label       = "static-asset"         optional, shown in the routing reason
# prefix + extensions together = "under this dir AND one of these types".
# A rule with none of prefix/path/extensions matches NOTHING (guarded, so a
# stray `{tier=...}` row can't silently swallow the whole diff).

[[e2e.rule]]              # inert assets under the static tree -> static
tier       = "static"
prefix     = "app/webapp/static/"
extensions = ["svg", "png", "jpg", "webp", "ico", "woff2", "webmanifest"]

[[e2e.rule]]              # a vendored HTML fragment is inert markup -> static
tier       = "static"    # (its .css/.js siblings are NOT here -> fall to full)
prefix     = "app/webapp/static/_vendored/"
extensions = ["html"]

[[e2e.rule]]             # real browser surface -> full
tier   = "full"
prefix = "app/webapp/"

[[e2e.rule]]             # backend python -> no browser impact -> none
tier       = "none"
prefix     = "src/"
extensions = ["py"]
```

See this repo's own `.fleet.toml` for the complete worked example the scaffold ships.

### Rule-writing guidance

- **List `full` and `none` rules explicitly; let `unclassified` catch the rest.** Anything you don't classify falls to `full` by design. That is safe (over-tests) but noisy — if the gate keeps running `full` for diffs you expected to be `skip`, a path is unclassified and wants a `none` rule.
- **CSS/JS route to `full`, not a curated subset.** Global stylesheets and the WebKit projection are exactly where layout regressions surface; a hand-maintained "layout subset" is both drift-prone and an under-testing risk. Keep static assets to genuinely inert file types.
- **Order matters.** A `static` rule for `_vendored/**.html` must come *before* the `full` rule for the enclosing `app/webapp/` prefix, or the broader rule wins first and the fragment routes to `full`.

## How the gate consumes it

`scripts/classify_e2e.py` is the mechanism. It:

1. reads the `[e2e]` table from `.fleet.toml` (fail-safe to `full` if absent/invalid);
2. computes the changed-file set — the union of `main...HEAD`, working-tree edits (`git diff HEAD`), and untracked files, so a *pre-commit* run classifies correctly;
3. classifies each path (first match wins) and takes the worst tier;
4. prints a machine-readable block the PowerShell gate parses:

```
E2E_TIER=static
E2E_BROWSERS=chromium
E2E_PYTEST_TARGET=tests/e2e/test_smoke.py
E2E_REASON=static-asset: app/webapp/static/icons/foo.svg
```

`verify-before-ship.ps1` runs the byte-compile + non-e2e pytest phases **unconditionally** (they already cover backend Python), then routes **only** the browser phase on `E2E_TIER`. On CI (`$env:CI -eq "true"`) routing is bypassed and the full suite always runs — the local gate is where routing is proven first.

Run it standalone to see how the current branch would route:

```powershell
& .\.venv\Scripts\python.exe scripts\classify_e2e.py            # classify the live diff
& .\.venv\Scripts\python.exe scripts\classify_e2e.py a.js b.svg  # classify an explicit list
```

## Anti-drift guard

A routing table is only safe if it stays honest as the layout evolves — a new view directory that nobody adds a `full` rule for would silently route to `skip` if some broader `none` rule swallowed it. Two things guard against that:

- **The `unclassified → full` fail-safe** means a *new, unclassified* path over-tests rather than under-tests. Drift fails safe by construction.
- **`tests/test_classify_e2e.py`** loads the real `.fleet.toml` and asserts representative paths (a vendored CSS, an app page, a backend module, an SVG asset) each land in the tier their rule intends. An edit that silently under-routes a real e2e surface fails there.

Keep both. When you add a new e2e-relevant directory, add its `full` rule to `.fleet.toml` **and** a representative assertion to that test, in the same PR — the same anti-staleness contract as the `.fleet.toml` `description` field and `docs/architecture.mmd`.
