# Diff-proportionate e2e routing

The pre-ship gate (`scripts/verify-before-ship.ps1`) used to run the whole `tests/e2e` browser suite on every change, regardless of what the diff touched. For a dual-projection Playwright suite that is minutes of Chromium + WebKit for a diff that changed one backend function or one SVG — pure cost, no added signal.

**Diff-proportionate routing** fixes that: the gate's browser phase classifies the branch's changed files against a per-project rule table and runs a browser slice *proportionate* to the diff. It is **fail-safe** — any uncertainty escalates to the full suite, never narrows it — and **automatic**, driven by `git diff`, with no manual `--fast` flag.

This was proven first in `app-launcher` (its `scripts/classify_e2e.py`, issue #568 / PR #574) and promoted here as a parameterized fleet convention (`project-scaffolding#180`). The difference: app-launcher hardcoded *its* layout into the classifier; the scaffold version reads the rules from each repo's own `.fleet.toml`, so the **mechanism** is shared and the **rules** are declared per-project.

## Who this applies to

Only web-app-shaped repos with a real browser e2e suite benefit — the dual-projection Playwright apps (grocery, whatsapp-radar, family-accounting, mathgamesforkids, life-os, website, home-automation) and this scaffold itself. A pipeline repo with no `tests/e2e/` has nothing to route; it simply declares no `[e2e]` table and the gate keeps running whatever `pytest` it already runs.

## The tiers

The gate's browser phase runs one of three tiers, plus an optional narrowing of `full` (below), chosen by the **worst** (highest) tier any changed file maps to:

| Tier | When | What runs |
|---|---|---|
| `skip` | every changed path matched a declared `none` rule (backend / docs / tooling only) | no browser suite at all |
| `static` | the worst-matching path is a `static` rule (inert assets — images, fonts, an inert vendored HTML fragment) | the narrow `static_pytest_target` (e.g. the smoke test), on `static_browsers` |
| `full` | any path matched a `full` rule, **or matched no rule at all**, **or** the diff is empty, **or** the repo declares no usable `[e2e]` table | the whole `full_pytest_target` (default `tests/e2e`) |
| `surface` | the diff would route `full`, but every `full`-tier path belongs to exactly one declared `[[e2e.surface]]` | that surface's `pytest_targets` (plus `static_pytest_target` if a static path rides along), suite-default browsers |

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

## Surfaces — narrowing `full` to one slice of the suite

A repo whose suite has grown past a handful of tests pays for the whole of it on every `full` diff, even when the change sits squarely inside one view. `[[e2e.surface]]` entries let the repo say which tests cover which paths (`project-scaffolding#258`, measured cost in `fleet-config#849`). They are optional: with none declared, routing is exactly the three tiers above.

```toml
[[e2e.surface]]
name           = "nav"
prefixes       = ["app/webapp/static/_vendored/nav/"]   # and/or exact `paths`
paths          = ["tests/e2e/test_vendored_nav.py"]
pytest_targets = ["tests/e2e/test_vendored_nav.py"]      # one or more test paths
```

The classifier narrows to `surface` **only** when every one of these holds; otherwise the verdict stays whole-suite `full`:

- no changed path is unclassified (the rules come first; a surface can never rescue an unmatched path);
- every path whose rule tier is `full` **or `static`** matches a surface, and exactly one (a path claimed by two surfaces is ambiguous). "Inert" markup can still be the page another harness drives, so a static path no surface owns keeps the whole suite;
- all of those paths belong to the **same** surface (a diff spanning two surfaces runs everything);
- the diff does not touch `.fleet.toml` or `scripts/classify_e2e.py` — a change to the surface map is never judged by that same unreviewed map — and no path contains a `..` segment;
- the surface declaration is usable. Every entry needs a `name` made only of `[A-Za-z0-9_.-]`, because names are echoed into the `E2E_*` lines the gate parses. It needs at least one matcher, and every `prefixes` entry must end in `/` so `app/board` can never claim `app/boardroom/`. `pytest_targets` must be a non-empty list of relative, whitespace-free paths that exist inside `full_pytest_target`, with no `..` and no absolute path. Names must be unique. One bad entry disables **all** surfaces, and the reason is appended to `E2E_REASON` on a rule-driven `full` verdict (an empty diff, a `skip` or a `static` verdict never consults surfaces).

Paths routed `none` ride along silently; a `static` path inside the surface adds `static_pytest_target`. The gate prints `E2E_TIER=surface`, `E2E_SURFACE=<name>` and a space-separated `E2E_PYTEST_TARGET`, which `verify-before-ship.ps1` splits into separate pytest arguments. Browsers are the suite default, exactly as for `full`.

**Surface-writing guidance.** A surface owns a feature's own files and its own tests, nothing shared. Keep global stylesheets, shared JS, `conftest.py`, shared test helpers and page shells out of every surface, so a change there still runs the whole suite. When one harness mounts on another surface's page (this repo's nav harness loads the component gallery), list that harness in the owning surface's `pytest_targets` too. Pin every surface in `tests/test_classify_e2e.py`, with one path that narrows and one shared path that must not, in the same PR that declares it.

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

A `surface` verdict adds one line and a space-separated target:

```
E2E_TIER=surface
E2E_BROWSERS=
E2E_PYTEST_TARGET=tests/e2e/test_vendored_components.py tests/e2e/test_vendored_nav.py
E2E_REASON=surface components: app/webapp/static/_vendored/card/card.css
E2E_SURFACE=components
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

## Diff-proportionate e2e routing (`.fleet.toml` `[e2e]` + `classify_e2e.py`)

Moved verbatim from `CLAUDE.md` (`#254`) so the always-on file stays under its size cap. `CLAUDE.md` keeps each section's heading, its *apply only if* gate and one-line rules, and points here for the full procedure, reasoning, snippets and decision records. Headings match `CLAUDE.md`'s, so a reference to a section by name resolves in either file.

*Apply only if this project has a browser e2e suite (`tests/e2e/`) wired into `verify-before-ship.*`.*

Makes the local gate's browser phase proportionate to the diff instead of running all of `tests/e2e` every change. Proven in `app-launcher` (`scripts/classify_e2e.py`, `#568`/PR `#574`), promoted here parameterized.

- **Mechanism shared, rules declared per-project.** `scripts/classify_e2e.py` reads an `[e2e]` table from the repo's own `.fleet.toml` (paths→tier map). TOML so stdlib `tomllib` loads it with zero custom parsing, rules versioned beside the code they classify. `.fleet.toml` is the single auditable home for the routing table.
- **Three tiers, worst-wins across the diff, plus an optional `surface` narrowing of `full` (#258):** `skip` (every changed path declared `none` — backend/docs/tooling) — no browser suite runs; `static` (worst path declared `static` inert asset) → narrow `static_pytest_target`; `full` (any `full` path, any unmatched path, empty diff, or no usable `[e2e]` table) → whole `full_pytest_target`.
- **Fail-safe is the point — uncertainty escalates, never narrows.** Unrecognized path, mixed diff, malformed/absent table all route to `full`. The table can only shrink an already-recognized-narrow diff, never a matched change further. CSS/JS route to `full` (no curated "layout subset" — drift-prone, under-testing risk); `static` stays to genuinely inert types (images, fonts, inert vendored HTML fragments). Rules are first-match-wins — declare specific `static` rules before the broader `full` prefix they sit under.
- **Wiring:** `verify-before-ship.*` runs byte-compile + non-e2e pytest **unconditionally**, then routes **only** the browser phase on the classifier's `E2E_TIER`. On CI (`$env:CI`) routing is bypassed, full suite always runs.
- **Anti-drift guard mandatory — two required:** the `unclassified→full` fail-safe, **and** `tests/test_classify_e2e.py` loading the real `.fleet.toml` and asserting representative paths land in their intended tier. New e2e-relevant directory → add its `full` rule to `.fleet.toml` **and** a representative assertion to that test **in the same PR** (same anti-staleness contract as `.fleet.toml` `description` and `docs/architecture.mmd`).
- **Ref:** full schema/rule-writing: `docs/e2e-routing.md`. Web-app-shaped adopters (grocery, whatsapp-radar, family-accounting, mathgamesforkids, life-os, website, home-automation) get one-line pointer issues for follow-on adoption — not scoped here. (`#180`; source instance `app-launcher#568`.)
