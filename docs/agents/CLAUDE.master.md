# Project Instructions

Canonical instructions for AI coding agents in this repo. Claude Code reads it as project memory; other agents (Cursor, Codex, …) reach it via the one-line `AGENTS.md` pointer.

> **Scope — project-shaped guidance only.** This master owns only what is *specific to a project's shape* (Streamlit, GitHub-Actions CI, e2e UI testing, tray / long-lived process), each section gated *"apply only if…"*. **Universal** dev-workflow directives (plan mode, asking, before/while editing, execution, conventions, git, branch & PR pipeline, planning, documentation discipline, senior-dev check) live once in `fleet-config/global-CLAUDE.md` (installed as `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`) and are **not** restated here. Test for any rule: *"would it apply to a bare repo with no app?"* Yes → global; no → here. Never both — `/context-audit` enforces the split weekly. (Standard: `project-scaffolding#68`.)

Three conventions that apply to every section below, stated once:

- **Issue refs are `project-scaffolding`** unless another repo is named.
- ***(PWA)*** in a heading = *apply only if this project serves a FastAPI + static PWA web app; Streamlit POC spikes are exempt*. Other gates are spelled out under their own heading.
- **Don't diverge, and don't re-author.** Every convention, vendored component and token contract below is owned *here*: fix it in this scaffold and re-vendor / propagate downstream, never fork it in a consuming app. Each section closes with its reference docs + decision record.

## Agent config artifacts (`AGENTS.md` pointer; `.agents/` / `.codex/` gitignored)
*Applies to every repo — app or not.*

- **`AGENTS.md` is a committed one-line pointer to `CLAUDE.md` — never a find-replaced copy.** Machine-scope instructions are the single global file symlinked into each agent home (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, …) by `fleet-config/install.ps1` — static, so drift-free by construction: no generator, no sync step.
- **`.agents/` and `.codex/` are gitignored, never committed** — per-repo auto-generated mirror/tooling noise; the real Codex config lives machine-scope in `~/.codex/`. This scaffold's `.gitignore` excludes both while deliberately **not** ignoring the committed `AGENTS.md`.
- **Don't diverge** — a clone inherits the pointer and the two `.gitignore` lines. (`#28`.)

## Streamlit conventions
*Apply only if this project uses Streamlit.*

- `st.set_page_config(layout="wide", page_title="...")` MUST be the first Streamlit call.
- Use `width="stretch"` (and `width="content"` where appropriate). **Never** introduce new `use_container_width=True` — deprecated; migrate existing uses when you touch that code.
- All mutable state in `st.session_state`. No module-level globals.
- `@st.cache_data` for DataFrames/files; `@st.cache_resource` for DB clients/models.
- Every widget needs a stable, explicit `key=`.
- UI code only in the UI directory (e.g. `app/`); data logic in the non-UI package (e.g. `src/`). Never import `streamlit` from non-UI code.
- User feedback via `st.error()` / `st.warning()` / `st.success()`, not `st.write()`.
- **App layout:** the main file (e.g. `app.py`) handles only page config, shared state, the sidebar, and routing. Default to native multipage navigation — `st.navigation` + `st.Page`, one view per file exposing a `render()` function. `st.tabs()` for sub-sections *within* a view; a sidebar radio only when asked.
- **Ask before assuming (Streamlit specifics):** `st.session_state` key names & scope; caching strategy (`@st.cache_data` TTL vs `@st.cache_resource`); widget `key=` names & input sources; page placement (new page vs a section in an existing one).
- **Custom CSS/JS hooking Streamlit's internal DOM is fragile** — raw `data-testid` selectors are undocumented and rename between versions; `position: sticky` inside a `st.container(key=...)` breaks on Streamlit's per-element `stLayoutWrapper` divs. Gotchas + fix: `docs/streamlit-css-hooking-gotchas.md`.

## Web-app visual identity (fleet design system) *(PWA)*

A fleet web app inherits its look **and** its navigation; it re-authors neither. `fleet-config` owns the *spec* (`design.md` + `design.dark.md`, junctioned into `~/.claude`, plus `/design-sync`); this scaffold owns the *vendored implementation* (`app/webapp/static/_vendored/`).

- **Tokens come from the spec, not from you.** Wire your CSS custom properties (defined in your app's `:root` / `[data-theme]` blocks) to `~/.claude/design.md` (light) + `~/.claude/design.dark.md` (dark) — colors, typography, spacing, radii. **Don't** copy the spec into your repo; **don't** invent a second accent or per-app palette. `/design-sync` reports drift.
- **Nav is vendored, not re-implemented.** The floating bottom-tab pill (desktop segmented control → mobile pill — the fleet *navigation contract*) comes from `app/webapp/static/_vendored/nav/` (`nav-tabs.js` + `nav-tabs.css` + `nav-tabs.html`). Copy the folder **verbatim**; adapt only your markup (which tabs) and the `storageKey`. The nav markup must be a direct `<body>` child and sibling of `<main class="app">`, **never** nested inside the content wrapper/scroller — iOS captures fixed-position descendants of scrollers and anchors them to short-tab content instead of the viewport (`home-automation#232`). Same "copy byte-for-byte, never fork per-app" rule as the tray's `single_instance.py` (`tray_lifecycle.ps1` moved to a shared machine-local copy in `#153` — see "Restart and verify before hand-off").
- **`_vendored/` is the UI component channel.** New shared HTML/CSS/JS components live under `app/webapp/static/_vendored/<component>/`, normalized from the best existing fleet implementation. Don't hand-copy a sibling app's snippet into a new app — vendor it from here. Convention + how to add one: `app/webapp/static/_vendored/README.md`.
- **Ref:** the vendored-component + token-contract ownership rule above. (Standard: `#79`; aligns to `fleet-config#178`.)

## UX surface — diff-keyed design-conformance gate *(PWA)*

When an issue touches a web app's UX, the finish flow runs a **gate** checking the change still conforms to the spec *and* that the rendered view isn't visually broken — the don't-introduce-new-drift arm of the section above, not a duplicate of the periodic fleet-wide audit (`fleet-config#180`).

**Two distinct checks — keep them separate; a real gate uses both, scoped to the diff.** A *token check* (`/design-sync`-style) diffs the CSS custom properties (light + dark) and the nav contract against the spec: static, no browser, **never renders the page** — catches "accent drifted", blind to "nav pushed off-screen / cards overlap". A *visual verification* (`verify`-style) launches the live app, drives the touched view in a headed browser, and screenshots it — the only check that *sees* the result, and the token-expensive leg.

**Each project declares a `## UX surface` block in its own `CLAUDE.md`** — the per-project *instance* the skills read, exactly as `## CI expectations` does; don't inline these paths into the skill. **This scaffold ships the block below as a _live_ declaration, not a fenced sample**, so a clone inherits a parseable block and turning the gate on is a one-word edit (`design spec applies` → `yes`, then adapt the paths/views). A repo with no web UI leaves it `no` and the gate is a permanent no-op. Keep the block under this heading; `ux_surface.py` tolerates the descriptive `— …` suffix, so do **not** add a second `## UX surface` heading (the parser matches this one first and would read nothing).

**The live block for this repo** — edit these lines in place; the skills read exactly them:

- design spec applies: no        # flip to `yes` once this repo serves a FastAPI + static PWA; `no` = gate no-ops
- paths:
  - app/webapp/static/**/*.css
  - app/webapp/templates/**
  - app/webapp/static/**/*.{js,html}
- key views:                     # used only by the `ux-full` whole-app sweep
  - /          (home + bottom nav)
  - /settings

**The gate contract (the shared skill behavior):**
- **Deterministic, diff-keyed — not a per-run LLM judgment.** Trigger is purely: does `git diff <main>...HEAD` intersect the declared `paths`? Yes → gate runs. No → skip silently and **state it** in the finish summary (`no UX surface touched`). Same path-keyed mechanism as the `## CI expectations` e2e-surface skip; zero added cost on the ~90% of issues touching no UX.
- **Cheap design-aware load at `/issue-start`.** When the picked issue is *likely* to touch the UX surface, read `~/.claude/design.md` + `design.dark.md` **before** building — two file reads, no browser. No `/design-sync` and no screenshot at start.
- **Gate at `/issue-finish` (and `/issue-yolo`), only when the diff touched the surface** — two legs:
  - **Token check, fix-now semantics.** Compare the touched UX files (CSS custom properties light + dark + the nav contract) to the spec and **fix material drift in this branch before merge**. Deliberately unlike vanilla `/design-sync`, which files-and-defers a `design-drift` issue — the finish gate's job is to **not introduce** drift. (Vanilla `/design-sync` stays as-is for the periodic sweep.)
  - **One screenshot of the touched view** via the `verify` skill, attached to the PR body — eyeball nav pill, layout, palette against the spec. Diff-scoped, never a whole-app sweep by default.
- **Manual overrides** (mirroring `/issue-start`'s `now`/`plan`): `ux` / `design` forces the gate even if the diff looks code-only; `no-ux` skips it when the detector over-fires; `ux-full` audits the whole app's `key views` — the one expensive path, opt-in only.
- **Materiality bar** (from `/design-sync`): a 1-unit radius/spacing nitpick is not a blocker; a wrong canvas color, a missing dark theme, a hand-rolled nav, or a visibly broken layout is.
- **Keep-the-human-in-control.** The agent always **states** the gate decision (ran / skipped / `ux-full`, plus any drift it fixed) in the finish summary, so the user can veto.

**Where each piece lives:** convention + block default here; the **skill mechanism** in `fleet-config` `skills/issue-{start,finish,yolo}/SKILL.md` (`fleet-config#195`); the **per-project instances** in each project's own `## UX surface` block; the periodic fleet-wide drift sweep is separate (`fleet-config#180`). Browser screenshots must go through the `verify` skill's stealth-Chrome launch (real Chrome, no automation infobar, per the global `CLAUDE.md`) — never re-inline launch args. (`#83`.)

## HTTPS provisioning *(PWA)*

An installed PWA needs HTTPS (Service Workers + Web Push are HTTPS-only); which path you take is decided by **how the app is reached remotely**.

- **Reached over Tailscale → `tailscale cert` (preferred).** Provision a **real Let's Encrypt leaf** for the tailnet MagicDNS name with `scripts/gen_tailscale_cert.py`. Tailscale owns the `ts.net` domain and answers the ACME DNS-01 challenge: **no public DNS name, no HTTP-01/DNS-01 setup, no inbound exposure**, and **zero per-device trust steps**. *Simpler* than the self-signed dance, not overkill. One-time prereq: enable HTTPS in the tailnet admin console (**DNS → HTTPS Certificates**), once per tailnet.
- **Auto-renew on startup is mandatory.** The LE leaf is **~90 days** (vs a self-signed root's 10 years), so a manual re-issue *will* be forgotten. `gen_tailscale_cert.py --check` renews **only** a `.ts.net` cert expiring within ~30 days, **no-ops a self-signed cert**, and never blocks startup on error. Wire `--check` into the **app's own webapp launcher** (e.g. `webapp.bat`), before uvicorn binds — **not** the generic `tray.bat.template` (vendored tray lifecycle; cert provisioning is app-specific). Reference wire-up: `grocery-shopping-automation`'s `webapp.bat`.
- **LAN-only / no Tailscale → self-signed CA (fallback).** Keep the self-signed CA + leaf (`gen_ssl_cert.py`) and the per-device trust dance (`certutil -user -addstore Root ca.pem` + the full-Chrome-restart gotcha; iOS `/install-ca` `.mobileconfig` + Certificate-Trust toggle). Correct **only** when there is no tailnet. The in-app `/install-ca` Settings affordance (`#74`) is scoped to this fallback — a `tailscale cert` app does not ship it.
- **Ref:** full procedure (commands, admin-console step, iPhone install): `docs/app-onboarding.md` §2–§3. (`#89`.)

## Webapp PWA required surfaces (build-identity footer + Settings/CA-install) *(PWA)*

- **Build-identity footer — `GET /api/version` → `{git_sha, built_at}`.** Capture the values **once at module load** via a hardened `git rev-parse --short HEAD` (`git -C <project-root>`, `stdin=subprocess.DEVNULL` + `creationflags=CREATE_NO_WINDOW` so the windowless tray never flashes a console), and render a `Build: <sha> · <ts>` line as a plain `<p>` **outside every card**. A `/healthz` 200 passes on a stale process, a matching `git_sha` does not — the `/issue-finish` + `/issue-yolo` tray-restart verification **depends on this endpoint existing**. It is **auth-gated** (loopback bypasses; the PWA attaches the bearer via the page's `jsonApi`) so a build SHA is never exposed to an unauthenticated remote caller. The footer is **universal** — present regardless of how HTTPS is provisioned.
- **Settings block — a collapsible `⚙️ Settings` `<details>` with an Install-certificate link.** The every-PWA portion is an **Install certificate** link to `/install-ca` (the route serving the iOS `.mobileconfig`). `/install-ca` is **auth-exempt**, so the link is a plain `<a href>` navigation that works over Tailscale without a token — **not** a `jsonApi` fetch. Include a short iOS trust how-to beside it. The block's **app-specific** contents (config fields, passkey/WebAuthn, tunnel status) are *not* part of the standard — only the collapsible block + the CA-install affordance are.
- **The CA-install link is conditional on the HTTPS path (ties to `#89`).** It exists only to make the self-signed-CA trust dance bearable, so it ships **only** on the self-signed / LAN-only fallback; a `tailscale cert` app **omits or hides** it. The `/api/version` footer stays regardless.
- **Ref:** the scaffold ships no starter FastAPI server today, so this is documented, not seeded — a vendored `_vendored/settings/` component is a separate future step (see `app/webapp/static/_vendored/README.md`). Reference implementations: `app-launcher` `app/webapp/routers/misc.py` + its `static/{index.html,main.js}`, and `home-automation`. (`#74`.)

## Webapp PWA static-asset cache-busting (`CachingStaticFiles` + fleet hash) *(PWA)*

iOS Safari — installed home-screen PWAs especially — heuristic-caches static assets served by a bare Starlette `StaticFiles` mount (only `ETag`/`Last-Modified`, **no explicit `Cache-Control`**): after a deploy + tray restart the device keeps running the **old cached JS/CSS** while `/api/version` reports the new build, and only deleting + re-adding the PWA clears it. Every fleet PWA ships the same fix: a **required convention**, not an optional extra.

- **One canonical reference, copied — not re-derived.** `home-automation/src/static_versioning.py` plus the `CachingStaticFiles(StaticFiles)` subclass (`home-automation/app/webapp/server.py`); adapt nothing but the static dir. Canonical method names are **`BuildInfo.stamp_html` / `stamp_js`** (wrapping `rewrite_index_html` / `rewrite_js_imports`) — one API, resolving the old photo-ocr `stamp_js` vs voice-transcriber `rewrite_js_imports` split.
- **Fleet hash, not a naive per-file hash.** The webapp is an ES-module graph (`index.html` → `main.js` → imported modules), so a per-file hash goes stale on transitive edits (`state.js` changes, `main.js`'s bytes don't). Use one **fleet hash** = a single SHA-256 over the concatenation of every hashable file's per-file hash; any edit to any module rotates *every* `?v=` stamp.
- **Stamp idempotently, degrade gracefully.** The import/href regexes also capture an existing `?v=…` and replace it, so re-stamping an already-served body is safe; an unreadable static dir or missing file falls back to **unstamped** URLs rather than crashing the page.
- **Per-suffix `Cache-Control`; the shell always revalidates.** `.js`/`.css` get `public, max-age=31536000, immutable` (safe because the fleet hash is the cache key); manifest/icons get `public, max-age=86400`. The **shell** (`index.html` root route) is served `Cache-Control: no-cache, must-revalidate` — otherwise a cached shell still points at the old entry module and the hashing buys nothing.
- **Ref:** trimmed `CachingStaticFiles` + fleet-hash reference snippet: `docs/app-onboarding.md` §4. Service workers / offline caching are deliberately **not** used in the fleet. (`#78`.)

## Windows event-loop pinning (uvicorn) *(PWA)*

- Every uvicorn spawn point (tray subprocess spawn via `manager.py`, a programmatic `uvicorn.run()`, `.bat` launcher scripts, e2e autoboot spawns) must pass a pinned selector-loop factory (`--loop`/`loop=`) — asyncio's default Windows proactor loop wedges the listening socket on any aborted client connection (`app-launcher#388`). Worked shim + rationale: `docs/app-onboarding.md` §1; reference implementation: `app-launcher`'s `app/webapp/event_loop.py` (`selector_loop_factory`).

## Windows console-subprocess suppression (`CREATE_NO_WINDOW`)
*Apply only if this project runs a long-lived Windows process (tray, daemon, GUI) without its own console — e.g. launched via `pythonw` — that shells out to a console-based CLI tool (`docker`, `nvidia-smi`, `git`, `taskkill`, …).*

- Every console-tool subprocess call (`subprocess.run`/`subprocess.Popen`, `asyncio.create_subprocess_exec`) must pass `creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0` — a console-less parent makes Windows allocate a fresh console per child, flashing a visible window (`#13`). Centralize behind one small helper imported everywhere rather than re-inlining the literal at each call site — `asyncio.create_subprocess_exec` accepts the same flag and is easy to miss vs the sync API. The helper belongs in the project's non-UI package; this scaffold ships `src/no_window.py`, imported as `from src.no_window import NO_WINDOW` (`#209`).
- **A vendor-verbatim module is the one exception, and it is not drift.** A file copied byte-identical into adopter repos (this scaffold's `$VendoredModules` list in `scripts/verify-before-ship.ps1` — e.g. `tests/e2e/_browser_sweep.py`, `scripts/classify_e2e.py`) cannot import the shared helper: the import would not resolve in a consumer's tree, and the hash-verified bytes must stay self-contained. Those files derive the flag locally *on purpose*, with a comment saying so — don't "fix" them into an import, and don't count them when auditing for re-derivation.
- A standalone entry point (a `scripts/` CLI, a test helper launched as a subprocess) has its own directory as `sys.path[0]`, not the repo root, so it needs one `sys.path.insert(0, <repo root>)` before the import. Keep the shared helper stdlib-only and side-effect-free so that import is safe even under a stripped-down venv with no site-packages.
- **Never add `DETACHED_PROCESS` on top — it neither suppresses the window nor escapes a subtree kill, so no case here wants it.** Measured from a genuinely console-less `pythonw` parent on this machine (`#221`): bare `CREATE_NO_WINDOW` suppressed the child's console every run, while `DETACHED_PROCESS` alone, `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, and `CREATE_NO_WINDOW | DETACHED_PROCESS` **each** let Windows Terminal host a visible window — combining the two does not make `CREATE_NO_WINDOW` win. `global-CLAUDE.md` owns the compatibility rule (the two are mutually exclusive, `local-llm-hub#282`); defer to it rather than restating a local version. And keeping a long-lived child alive across a tray teardown is a **re-parenting** problem, not a creation-flag one — `taskkill /T` walks the PID tree, which no creation flag changes, so use the `cmd /c start` re-parenting recorded under "Restart and verify before hand-off" below.
- Related trap: a `pythonw` child launched without a redirected `stdout`/`stderr` crashes on its first log write (no console to write to) — always give it a real target (pipe or file).
- Worked helper: `docs/app-onboarding.md` §1.

## FastAPI + SQLite connection lifecycle (one `get_db` `Depends` dependency)
*Apply only if this project is a FastAPI app backed by SQLite.*

- **One dependency owns the connection.** One `get_db()` connects, sets `row_factory = sqlite3.Row` + `PRAGMA journal_mode=WAL`, then `try: yield / finally: conn.close()`. Handlers take `db: sqlite3.Connection = Depends(get_db)` rather than opening their own — the connection closes even when the handler raises, and centralized setup (pragmas, row factory, timeout) can't drift between handlers. Acceptance: a derived app has **zero** per-handler `sqlite3.connect(...)` calls in its routers.
- **SQLite + stdlib `sqlite3` stays the fleet default.** This convention is only about the *lifecycle dependency* — no ORM, no async driver, no connection pooling. (Apps that legitimately need a long-lived single connection — none currently identified — are the documented exception.)
- **Ref:** canonical `get_db` + `Depends` reference snippet: `docs/app-onboarding.md` §4. (`#96`; source instance `whatsapp-radar#100`.)

## Outbound-connection discipline (pooled sessions, backoff, bounded fan-out, no leaked children)
*Apply only if this project runs a long-lived process (tray, daemon, webapp, poll loop) that makes outbound HTTP/TCP calls — to another local app, an external API, or hardware.*

Windows ephemeral-port exhaustion (global `CLAUDE.md`; `fleet-config#440`) makes a fresh-connection-per-call poller a whole-machine outage risk, not just a local inefficiency.

- **Reuse connections — is a `/propagate-vendored` component: `src/pooled_http.py` (manifest key `pooled_http`).** A bare `requests.get`/`requests.post` inside a poll loop, health check, or per-item fan-out is a **defect**, not a style preference: fresh connection, fresh `TIME_WAIT` port, every call. `build_session(pool_size)` returns a `requests.Session` with a sized, keep-alive `HTTPAdapter` mounted on both schemes, built once (e.g. at module import) and never reconfigured per call; `pooled_request(method, url, *, timeout, session=SESSION, **kwargs)` dispatches through it and retries **once** on `requests.exceptions.ConnectionError` — safe even for non-idempotent methods (the failed attempt never reached the server), so a sibling's restart surfaces as a clean reconnect. Vendorable because only pool size and target URL are call-site arguments, exactly the `single_instance.py` / `tests/e2e/_e2e_live_guard.py` pattern. Reference implementation: `app-launcher#605`'s `src/_loopback_http.py`. `requests` is a real added dependency for a project that vendors this file — **not** pulled into every scaffolded project's `requirements.txt`; only this repo's own copy (used to prove the module via its unit tests) declares it.
- **Back off what is failing — prose only, no vendored helper (yet).** Failures escalate the retry interval, success recovers it, so a permanently-dead endpoint settles at a slow retry rather than the hot-path cadence. Prose because there is no proven reference implementation to vendor from yet (`home-automation#537` still open); extract a shared backoff tracker once a real fix lands — propagate a proven fix, not a theoretical one.
- **Cap the fan-out — prose only.** Polling N devices/endpoints concurrently should bound concurrency (an `asyncio.Semaphore(N)` or equivalent around the poll loop) rather than firing all N at once every tick. A 2–3 line idiom that differs by concurrency model (`asyncio` vs `threading` vs a plain counter) — write it inline at the poll loop; too thin and framework-specific for a vendored wrapper.
- **Do not leak child processes — the sweep ships: `tests/e2e/_browser_sweep.py` (`#203`).** An e2e suite must close every browser/context it opens, including on a failed or interrupted run (a `finally`/fixture-teardown path, not just the happy path). The `pytest_sessionfinish` sweep **classifies before it kills** — a kill requires all three of: really running, parent dead, and working directory under the checkout this run owns. Blanket kill-by-image-name stays **forbidden** (it would take down another session's in-flight run, or the user's own Chrome — which is why Chromium is deliberately out of the sweep set). Two findings must survive any rewrite: an **already-exited helper is not a leak** (Windows keeps an exited process's object — and its `tasklist`/WMI row — alive while any handle to it remains, so it is unkillable *and* harmless; the sweep reports it and never fails the gate over it), and anything the sweep cannot establish (unreadable cwd, non-Windows host) reports as its own **unknown** verdict rather than folding into "clean". Full pattern, the measured abort-cascade matrix, and the PEB cwd-attribution trick: `docs/playwright-ui-testing.md` → "Post-run sweep for leaked browser helpers".

## GitHub Actions CI conventions
*Apply whenever this project adds a `.github/workflows/` file.*

- **Pin a dated Windows runner:** `runs-on: windows-2025`, never `windows-latest` (GitHub redirects `windows-latest` → `windows-2025`, deadline June 2026). For a Windows-only tray/daemon app spawning real processes (PTYs, uvicorn, Chromium), an OS image changing under you turns a green gate red with no code change.
- **Use Node-24 action majors:** `actions/checkout@v6`, `actions/setup-python@v6`, `actions/upload-artifact@v7` — not `checkout@v4` / `setup-python@v5` / `upload-artifact@v4`, which run on deprecated Node 20 (forced Node 24 from June 16 2026; Node 20 removed September 16 2026). Inputs unchanged for standard usage, so the bump is drop-in.
- **Trigger once per commit: `push:[main]` + `pull_request:[main]`** — `push` to `main` is the post-merge integration gate, `pull_request` to `main` validates every feature branch. Do **not** trigger `push` on feature branches (`push:` with no `branches:` filter, or `push: branches-ignore: [main]`): with a PR open, every branch push fires *both* events and runs the same gate **twice on the same commit**, and `branches-ignore: [main]` additionally *omits* the post-merge `main` gate, leaving the merge commit — which can differ from what the PR validated — never CI-gated. `concurrency` cannot fix this: `github.ref` differs between the events (`refs/heads/<branch>` vs `refs/pull/<N>/merge`), so they land in separate groups and both survive; it only collapses successive pushes to the *same* ref. The only thing given up — CI on a branch pushed but never PR'd — is a non-loss: `/issue-finish` always pushes and immediately opens the PR.
- **Run counts, wrong shape (`push: branches-ignore: [main]` + `pull_request`) → this convention:** feature-branch push with an open PR **2 → 1**; with no PR yet **1 → 0** (open the PR before you need CI); merge commit on `main` **0 → 1**.

Canonical pattern:

```yaml
on:
  push:
    branches: [main]          # post-merge integration gate on main only
  pull_request:
    branches: [main]          # validates every feature branch via the PR event

jobs:
  <job>:
    runs-on: windows-2025          # not windows-latest — pin the OS image
    steps:
      - uses: actions/checkout@v6        # Node 24 (not @v4 / Node 20)
      - uses: actions/setup-python@v6    # Node 24 (not @v5 / Node 20)
        with:
          python-version: '3.12'
      # ...
      - uses: actions/upload-artifact@v7 # Node 24 (not @v4 / Node 20)
        with:
          name: <name>
          path: <path>
```

**Sister-repo tracking:** a fleet repo still on the old runner/actions (`#25`) or the duplicate `push`-on-branches trigger (`#38`) carries a pointer issue back to the canonical decision record in `project-scaffolding`. Fix it before the deprecation deadline, not after.

**A red default branch files its own tracking issue — `main-gate-watch`.** Copy `.github/workflows/main-gate-watch.yml.template` to `.github/workflows/main-gate-watch.yml` and replace its one `__GATE_WORKFLOW_NAME__` token with the gate workflow's `name:`. On a `workflow_run` completion for that workflow — filtered `branches: [main]` (PR runs excluded; a PR's own gate is already visible in its checks) and gated on `conclusion == 'failure'` — it creates the `ci-red-main` label (`--force`, idempotent), comments `Still red on main at <sha>: <run-url>` on the open `ci-red-main` issue if one exists, else files `main's <gate> gate is red` (`bug` + `ci-red-main`, assigned to `github.repository_owner`). **The issue body's framing is the substance; the YAML is the easy part:** discounting a red gate for an unrelated PR is legitimate but is *a separate matter from fixing it*, and the issue stays open until `main` is green. Without it, "`main` is red" is nobody's finding — every individual observer correctly reasons past it and it never becomes anyone's problem (`whatsapp-radar#258` ran four days red exactly that way, via two markdown-only PRs in sequence; three fleet repos were found red in a single day, 2026-08-15).

- **Precondition, and it is not a formality: a `workflow_run` watcher can only observe a gate that runs in Actions on pushes to the default branch.** A repo whose gate is local-only (`verify-before-ship.ps1` / `pytest` on the developer's machine — *this scaffold included*) gets **zero** coverage from the file: it never fires, and its presence reads as coverage. Don't install it there. Such a repo's red-`main` detection is **unknown**, reported as its own state — never folded into green (same rule as every other unestablished fact).
- **Local-gate repos get a scheduled fleet-side sweep instead, not an advisory Actions gate** (decision, `#222`). Porting a Windows-desktop gate (real `.venv`, browsers, fixed ports, a tray) onto a hosted runner yields a *degraded subset*, and a green watcher over a subset is false coverage wearing a checkmark — worse than none, because it stops anyone looking. So: **the watcher where Actions runs the real gate; a scheduled sweep of the actual local gate everywhere else** — both filing the *same* idempotent `ci-red-main` issue so the two mechanisms converge on one tracker per repo, and a gate that could not be run reporting `unknown` with a reason. The sweep itself belongs in `fleet-config` as its own scheduled skill (not bolted onto `/audit-fleet`, whose bounded weekly cost depends on it never running per-repo workloads); it is unbuilt — until it exists, a local-gate repo has no automated detection and should say so.

## CI is advisory — `## CI expectations` block + e2e-surface skip rule
*Apply whenever this project has a `.github/workflows/` file **and** a local verification gate.*

**CI is advisory, not a required gate.** The fleet's e2e workflows run on repos with **no branch protection**, so their checks are not required to merge; the **local gate** (`scripts/verify-before-ship.ps1`, or `pytest + ruff + mypy`) is the contract. The agent must not treat `gh pr checks --watch` as a mandatory blocking wall.

**CI's only signal beyond the local gate is the e2e suite** — the local gate runs `pytest + ruff + mypy` but skips the Playwright leg (needs browsers + a live webapp), which is also the known-flaky part (browser/PTY input wedging on the slower hosted Windows runner). A diff touching **none** of the project's e2e surface gains nothing from waiting on CI, while a wedged WebKit browser can still block the merge up to the `timeout-minutes` cap.

**Each project declares a `## CI expectations` block in its own `CLAUDE.md`** (the per-project *instance* — durations, flaky leg, e2e-surface paths). `/issue-finish` reads it; don't inline these values into the skill. Block template (fill the bracketed values):

```markdown
## CI expectations
- Workflow `[.github/workflows/e2e.yml]`, job `[verify-before-ship]`, on every PR. **Advisory, not required** (no branch protection) — the local gate is the contract.
- Typical green: **~[N] min**. Investigate at **>[2N] min**; treat as wedged at **>[~4N] min**.
- Flaky leg: `[the Playwright WebKit/iPhone projection / PTY-input tests]` can wedge on the hosted runner. `timeout-minutes: [30]` caps a wedge. A wedge is a flake, not the diff.
- CI's only signal beyond the local gate is the **e2e suite** (skipped locally). Its e2e surface = `[app/webapp/, app/tray/, tests/e2e/, static assets, …]`. A diff touching **none** of these gains nothing from CI.
```

**What `/issue-finish` does with it (the shared skill mechanism):**
- **Skip-the-wait keyed on the e2e surface, not "docs vs code."** Diff touches none of the declared e2e surface and the local gate is green → merge on local-green and **state it** in the finish summary (e.g. `CI not awaited — store-only diff, no e2e surface touched`). Generalizes the old narrow `*.md`-only skip rule.
- **Proactive flake handling.** Read the expected duration from the block; the moment elapsed crosses the *investigate* threshold, stop waiting passively — inspect the run (`gh run view --job`), classify flake vs real failure, and for the *documented* flaky leg cancel + rerun **once** automatically, saying so. A second flake → stop and surface it to the user. **Never** rerun a real (non-flake) failure.
- **Keep-the-human-in-control.** The agent always **states** its CI decision (skip vs wait, plus any rerun) in the finish summary, so the user can veto. Auto-rerun is capped at **once** and only for the *documented* flaky leg. Nothing force-merges; because CI is advisory (no branch protection) no `--admin` override is ever needed. **If a repo later adds the `e2e` check as a *required* status check, the skip-rule must fall back to watching** — a required check cannot be skipped without `--admin`, and force-merging is out of scope here.

**Where each piece lives:** convention + block template here; the **skill mechanism** in `fleet-config` `skills/issue-finish/SKILL.md` step 5; the **per-project instances** in each project's own `CLAUDE.md` block; **sister-repo pointer issues** (start: `whatsapp-radar`, `app-launcher`) track adoption. Making the e2e leg actually stop flaking is a separate per-project fix — this convention makes a flake *cheap*, it does not cure it.

## Diff-proportionate e2e routing (`.fleet.toml` `[e2e]` + `classify_e2e.py`)
*Apply only if this project has a browser e2e suite (`tests/e2e/`) wired into `verify-before-ship.*`.*

Makes the local gate's **browser phase proportionate to the diff** instead of running all of `tests/e2e` on every change. Proven in `app-launcher` (`scripts/classify_e2e.py`, `#568` / PR `#574`), then promoted here **parameterized**.

- **The mechanism is shared; the rules are declared per-project.** `scripts/classify_e2e.py` reads an `[e2e]` table from the repo's own `.fleet.toml` (the file already carrying the fleet-map card), so a `paths → tier` map extends the declared-paths convention rather than adding a file. TOML so the classifier loads it with stdlib `tomllib` — zero custom parsing — and the rules stay versioned next to the code they classify. **`.fleet.toml` is the single auditable home for the routing table.**
- **Three tiers, worst-wins across the diff:** `skip` (every changed path is a declared `none` — backend/docs/tooling — so no browser suite runs), `static` (worst path is a declared `static` inert asset → the narrow `static_pytest_target`), `full` (any `full` path, **any unmatched path**, an empty diff, or no usable `[e2e]` table → the whole `full_pytest_target`).
- **Fail-safe is the whole point — uncertainty escalates, never narrows.** An unrecognized path, a mixed diff, a malformed/absent table all route to `full`. The table can only make an *already-recognized-as-narrow* diff run less; it can never make an unmatched change run less. CSS/JS route to `full` (not a curated "layout subset" — drift-prone, an under-testing risk); keep `static` to genuinely inert file types (images, fonts, inert vendored HTML fragments). Rules are first-match-wins, so declare specific `static` rules *before* the broader `full` prefix they sit under.
- **Wiring:** `verify-before-ship.*` runs byte-compile + the non-e2e pytest phase **unconditionally**, then routes **only** the browser phase on the classifier's `E2E_TIER`. On CI (`$env:CI`) routing is bypassed and the full suite always runs — the local gate is where routing is proven first.
- **Anti-drift guard is mandatory** — two guards, both required: the `unclassified → full` fail-safe, **and** a `tests/test_classify_e2e.py` that loads the real `.fleet.toml` and asserts representative paths land in their intended tier. When you add a new e2e-relevant directory, add its `full` rule to `.fleet.toml` **and** a representative assertion to that test **in the same PR** — same anti-staleness contract as the `.fleet.toml` `description` field and `docs/architecture.mmd`.
- **Ref:** the convention + the parameterized `classify_e2e.py` + the `[e2e]` schema live here; full schema reference and rule-writing guidance: `docs/e2e-routing.md`. Web-app-shaped adopters (grocery, whatsapp-radar, family-accounting, mathgamesforkids, life-os, website, home-automation) get one-line pointer issues for follow-on adoption — not scoped here. (`#180`; source instance `app-launcher#568`.)

## End-to-end UI testing
*Apply only if this project serves a browser UI (Streamlit, FastAPI, Flask, etc.).*

Two loops, kept deliberately separate. Don't conflate them. Full reasoning, setup, and bootstrap recipe: `docs/playwright-ui-testing.md`.

### Iterative verification (headed, agent-driven)
Use this during active development so I can watch the agent verify a change.

- Drive the running app via the **Playwright MCP server in `--headed` mode** (Claude Code, Codex CLI). For tools without MCP support, fall back to a small `playwright` Python script run via Bash with `headless=False`.
- Boot the app **once** on a fixed port (Streamlit default: 8501) and leave it running. Do NOT restart between iterations unless `set_page_config` or top-level imports changed.
- Prefer the a11y `snapshot` tool over `screenshot` — DOM is far cheaper than pixels in tokens. Screenshot only on failure or as final visual confirmation.
- Cap actions per cycle in the prompt (≤ 5 actions, then report). Stop and ask if the page state is unexpected; do not loop blindly.
- Target widgets via their stable `key=` (required by the Streamlit conventions above) using `page.get_by_role(..., name=...)` or `page.get_by_test_id(...)`.
- Do NOT create files under `tests/e2e/` for verification — it's throwaway, lives in the conversation only. Promotion to a permanent test is a separate, deliberate decision (see below).

### Regression suite (headless, pytest-playwright)
Optional. Lives at `tests/e2e/`. **Don't create the folder until the first regression test is actually justified.**

- Add a test only when all three hold: (1) silent breakage would hurt, (2) it can't be caught by a unit test under `tests/`, (3) the behavior has stabilized (not still in flux).
- Runs via `& .\.venv\Scripts\python.exe -m pytest tests/e2e/` (Windows) / `./.venv/bin/python -m pytest tests/e2e/` (POSIX). No LLM in the loop, zero per-run cost.
- **One shared session fixture boots the app — and any service dependencies** (a separate API process, a worker, a PTY host, …) — once per pytest run. Engine-agnostic: `streamlit run`, `uvicorn`, `flask run` are all just the launch command.
- **Default to isolation — boot a disposable instance; refuse before silently adopting.** With no opt-in env var set, the fixture boots its own fresh instance and, if the target port is already occupied, **refuses** (`pytest.exit`, naming the flag) rather than killing or reusing whatever's there — a bare `pytest tests/e2e` must never silently drive a live app the harness didn't start (`#191`).
- **Opt-in to *acting on* an occupied port is one loudly-named env var per project** (`LAUNCHER_E2E_LIVE`; this scaffold's `STREAMLIT_E2E_LIVE`) — never an opt-**out** flag (`E2E_FORCE_AUTOBOOT=1`-shaped names get the polarity backwards: forgetting to set them silently re-enables adoption).
- **What the flag permits is not the same everywhere — don't conflate the two shapes.** `app-launcher`'s `LAUNCHER_E2E_LIVE` means *read-only assertions* against the live tray, never a kill (`_require_live_tray` guard; `--e2e-autoboot` never adopts the live session-host on `:8446`, always spawns its own on a free port). This scaffold's `STREAMLIT_E2E_LIVE` means a kill-and-restart via `ensure_fresh_streamlit`, legitimate only because the target is a stateless, cheap-to-restart dev server *and* it goes through this repo's own canonical restart helper rather than a by-hand kill (`#197`). A repo adopting the vendored guard picks its own meaning and documents it; the guard's exit message points at that repo's `CLAUDE.md` rather than prescribing one. **Log** which instance — disposable vs acted-on-live — the suite is driving and why, so a hung run is diagnosable from its own output.
- **Isolate anything stateful — never adopt-and-mutate a host that holds the user's live work, even under the live opt-in.** The reclaim-on-opt-in rule above is safe only for a stateless, cheap-to-restart webapp. A host that owns user state or child processes (a session-host, a worker with in-flight jobs, a PTY host) must **always** get the harness's own disposable instance on a free port, injected into the dependent process via an env override — never the live fixed port, opt-in or not. Litmus test: *is the thing I'd be touching holding work the user would be upset to lose?* If yes, isolate unconditionally. Same bar, a **destructive test scopes to what it created**: snapshot pre-existing ids before acting, kill only the delta, never `.first` / "whatever's in the list" (`app-launcher#260`).
- **Is a `/propagate-vendored` component: `tests/e2e/_e2e_live_guard.py` (manifest key `e2e_live_guard`).** The *policy* — check the target port, refuse (`pytest.exit`, naming the flag) if occupied with no opt-in, otherwise log the decision — is shape-independent; only the port number, the flag name, and how the disposable instance boots are call-site parameters (`#191` shipped it inline as prose-only; `#194` reversed that). Vendored per the same pattern as `app/tray/single_instance.py` (mutex names are arguments) and `tests/e2e/_geometry.py` (selectors/budgets/theme are arguments) — copy the file byte-identical into an app's `tests/e2e/`, call `require_disposable_instance(port, flag_env_name)` from the fixture, and let `/propagate-vendored e2e_live_guard` hash-verify and re-vendor it fleet-wide. (`tray_lifecycle.ps1` is *not* a valid precedent — de-vendored to a shared machine-local copy in `#153`.) The adopter records the entry in its own `.fleet.toml`'s `[vendored]` table — never here; that table lives per-adopter, not in the source repo.
- **Boot failure is a hard failure — never `pytest.skip`.** A suite that skips when the app isn't up reports green on a build it never tested. Skip is fine for the *ad-hoc* "use whatever tray I have running" path; the *pre-ship* path must fail loud.
- Keep the suite small — target < 15 tests total. If you're tempted to add #20, delete two first.
- No Page Object Model. Too much ceremony for this size.
- Don't gate commits on e2e. Run on push or in CI, not in pre-commit.
- When you remove a feature, remove its e2e test in the same commit.

### Mobile / phone-first UI testing
*Apply only if the app's primary surface is a phone.*

- Project the regression suite onto **WebKit** with a device-emulation descriptor (Playwright ships iPhone / Android descriptors — viewport, user-agent, touch, scale factor). WebKit shares the iOS Safari rendering + JS engine, so it reproduces most "Safari is unhappy" bugs on a Windows/Linux box before they reach a real phone.
- Make the projection **always-on** — a parametrised `browser_name` / device fixture so every test runs the mobile projection too. An opt-in projection gets forgotten.
- WebKit-on-Windows is *not* real iOS: no iOS shell, no real WKWebView memory limits, no Apple keyboard, no Add-to-Home-Screen container. For the residual shell-only bugs, attach PC DevTools to a real phone via `ios-webkit-debug-proxy` (bridges the iOS Web Inspector to a local port Edge/Chrome DevTools can attach to). Playwright cannot drive real iOS Safari — only its bundled WebKit and the iOS Simulator on macOS.

## Verification (before declaring a task done)
Examples — adapt to the project's actual tooling.

Windows / PowerShell:
- Syntax: `& .\.venv\Scripts\python.exe -m py_compile <file>`
- Lint (if configured): `ruff check .`
- Tests (if any exist): `& .\.venv\Scripts\python.exe -m pytest`
- Streamlit boot check (UI changes): `& .\.venv\Scripts\python.exe -m streamlit run app/app.py --server.headless true`

POSIX:
- Syntax: `./.venv/bin/python -m py_compile <file>`
- Tests: `./.venv/bin/python -m pytest`

**Pre-ship gate (projects with an e2e suite).** Wire a single project-specific command — e.g. `scripts/verify-before-ship.ps1` — running the whole pipeline as one pass/fail: byte-compile → unit `pytest` → e2e suite (auto-booting the app per the harness rule in "End-to-end UI testing"). Mandatory before any UI-touching change is declared done. One command, can't half-skip. Do **not** substitute a bare `pytest` run that silently skips e2e when no server is up — that is how a regression ships looking green.

## Restart and verify before hand-off
*Apply only if this project runs a long-lived process (dev server, webapp, daemon, tray) without hot-reload.*

After verification — unless I said otherwise — restart that process so the change is actually live, and **confirm it**: a version/build endpoint or equivalent signal showing the running process reflects the new code, not just that it answers a health check (a stale process passes those fine). Report the build identifier. Never hand off "done" over a stale process.

**Restart safely.** Kill only *this* app's specific process, identified precisely (listening port / PID / window title) — never a blanket process-name kill (`pythonw`, `node`, `python`), which also takes down sibling apps and shared services.

**A 'start' script is usually not a 'restart' script.** Re-running `launch_app.bat` / `tray.bat` / `npm start` over a live instance typically spawns a duplicate (or silently no-ops if the port is bound). The pattern is **kill-then-start**. Document the project-specific recipe in this repo's own `CLAUDE.md` under `## This repository` — *which* process to kill (port / PID lookup), *which* command relaunches it, *what* signal confirms the new build (e.g. `GET /api/version` returning the current `git_sha`).

**A tray restart must reclaim the app's service ports by PID (orphan-proof), not just `taskkill /T` the tray subtree.** Service children (webapp, session-host, tunnel) orphan when the tray dies or is replaced, still holding their port; a subtree-only kill misses them — the fresh tray can't bind, silently fails, and the orphan keeps serving stale code while the restart *reports success*.

- For each fixed loopback port the app **definitively owns**, `--restart` finds the current listener, kills its owning PID, **then** starts. Scope the sweep to **this app's `.venv`** so siblings are never touched, and exclude any **mutex-shared** port (reclaiming it would kill the sibling's live process).
- Scope by the holder's **CommandLine**, *not* its process image path: on Python 3.14 Windows venvs a venv-launched `pythonw.exe` re-execs the base interpreter, so the image path reports the *shared base* while only the CommandLine carries the `.venv` path — an image-path guard never matches and the reclaim silently no-ops.
- **The full detect → kill → reclaim → start → verify lifecycle lives in one committed helper, shelled to with `-File` once** — never cmd `for /f` output capture or inline `powershell -Command "…"` (`#54`): both cmd-side forms return empty detection/reclaim data when `tray.bat` runs **non-interactively** (Git Bash → `cmd /c "tray.bat --restart"`, or a finisher skill's Bash tool), so nothing is killed and `--restart` degrades to a plain start — which **adopts** whatever already serves the port (`WebappManager.start()` → `OWNERSHIP_EXTERNAL`) and reports healthy. Only the reclaim forces new code to load.
- **Verify by served `git_sha` vs repo `HEAD`, never a `healthz` 200** (a stale adopted process passes health checks); a mismatch must exit non-zero.
- Since `#153`, `tray_lifecycle.ps1` is **not** vendored per-app: every `tray.bat` calls the ONE shared, machine-local copy owned by `fleet-config` at `%USERPROFILE%/.claude/tray/tray_lifecycle.ps1` (exposed by its `install.ps1` junction), and still hard-errors (never no-ops) if that path is missing, naming fleet-config's `install.ps1` as the fix. A tray app still vendors `app/tray/single_instance.py` byte-for-byte — it ships *with* the app rather than being shelled to.

Third tray-lifecycle gotcha, alongside **#12** (single-instance via a named mutex, not a bound TCP port) and **#13** (`CREATE_NO_WINDOW` when shelling out to console tools); no conflict with #12 — #12 *detects* a running instance, this is how a *restart cleans up* the previous one. Canonical `tray.bat` shape (idempotent start + verified reclaim-then-start) and full reasoning: `docs/windows-tray.md`; a copy-to-adapt `tray.bat.template` ships at the scaffold root (replace four `__PLACEHOLDER__` tokens — app name, tray-launch args, tray-match regex, owned ports).

**The canonical restart invocation is `tray.bat --restart` — call it, don't hand-roll the kill.** That one command *is* the restart: orphan-proof subtree-kill + per-`.venv` port reclaim + start, atomically. Automated finishers (`/issue-finish`, `/issue-yolo`) and any agent restart must run it rather than re-deriving a `Get-NetTCPConnection`/`taskkill` sequence — a hand-rolled kill catches only the listener it happens to find and misses the orphan the reclaim sweep exists to kill. The manual port-PID kill is a *fallback* for the rare app with no `--restart`, never the default; each tray app's `## This repository` section names `tray.bat --restart` plus the signal that confirms the new build is live.

**A tray's single-instance guard must hold *in the tray process* (a named mutex), and its adopt-or-spawn must be *race-safe*.** The **fourth** tray-lifecycle gotcha, alongside **#12** / **#13** / **#29**. The launcher `.bat`'s pre-launch CIM detection is necessary but not sufficient — two near-simultaneous `tray.bat` runs both read the process table before either tray is visible and both survive; per #12 the guarantee belongs to a named mutex the tray holds for its lifetime (acquire at the top of `run_tray()`; if already held, exit). Independently, a `WebappManager.start()` doing `status()`-then-`Popen` is check-then-act: two trays that both see "port free" both spawn a duplicate uvicorn (a TOCTOU race). Serialize the check-then-spawn with a named mutex keyed on the owned port so the loser **adopts** the now-listening service instead of spawning. Both are solved by one byte-identical primitive — `app/tray/single_instance.py` (`SingleInstance` + `cross_process_lock`) — shipped in the scaffold and **vendored verbatim** (only the mutex *names* differ per app). Full reasoning: `docs/windows-tray.md` (gotcha #4).

**The agent restarts a tray by invoking `tray.bat --restart` fire-and-forget, then verifying with a *bounded* poll — never a foreground launch or an unbounded wait.** A tray launcher holds the console it starts in, so a foreground tool call never returns and burns the 10-minute timeout. Call `--restart` non-blocking (background/detached) so the tool returns at once, then poll `GET /api/version` with a **hard timeout and attempt cap** (e.g. ≤30 s), asserting `git_sha == HEAD` and reporting the build line; **fail loud** on a slow/failed boot. A `/healthz` 200 is not enough.

A correct restart is **adopt / reclaim / spawn** — re-attach to healthy owned children, reclaim stale port-holders, spawn only what's missing — classifying children as **owned-and-cycled** (webapp/worker/cloudflared: live *inside* the tray subtree, die + respawn with new code, port in the reclaim list) vs **linked-but-independent** (a session-host + its PTY shells / launched apps: must **survive**). "Must survive" is enforced structurally: linked children are **spawned re-parented out of the tray subtree** via `cmd /c start` — `taskkill /T` walks the parent-child PID tree, so `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP` do **not** escape it, only re-parenting does (verified empirically) — and the fresh tray **re-adopts** them on start by port/identity. **Safety caveat:** until a tray with linked children is detach-compliant, `--restart` still kills those children — that tray's `CLAUDE.md` flags this and the agent confirms first. Mirrored in the `/issue-finish` finisher and the global restart skill (`#35`).

**Propagation freeze.** This repo vendors one channel verbatim into every sister repo that needs it: the web-app UI components (`app/webapp/static/_vendored/`) and, for tray apps, the imported `app/tray/single_instance.py` + `app/tray/watchdog.py` primitives. (`tray_lifecycle.ps1` left this model in `#153` — machine-local infrastructure, not app code; ownership story in `docs/windows-tray.md`, channel rule "does it ship with the app?" in `app/webapp/static/_vendored/README.md`.)

- A vendored-component fix does **not** propagate until this scaffold's own verification gate is green — for the tray helper that includes the behavioral e2e harness `tests/e2e/test_tray_lifecycle_behavior.py`, which drives the real lifecycle end to end against the canonical file (resolved via `resolve_tray_lifecycle_path()`), not just structural/grep asserts.
- A **second** bug in the same vendored component **within the same day** freezes propagation entirely — harden and soak at source, no partial re-vendor, then ship one cumulative wave once stable. (Tray cascade: `#144`–`#150`.)
- UI-component propagation is never a hand-filed per-repo issue; trigger criteria for the batched `/propagate-vendored` run live in `app/webapp/static/_vendored/README.md` ("Rules").

## Tray webapp self-heal (retry-with-backoff spawn + dead/wedged watchdog + breadcrumb log)
*Apply only if this project runs a Windows tray that owns a long-lived service (a uvicorn webapp, a worker, a tunnel).*

Covers the hours *between* deliberate restarts — without these three pieces the tray starts its webapp exactly once and never looks at it again.

- **Is a `/propagate-vendored` component: `app/tray/watchdog.py` (manifest key `tray_watchdog`).** Copy it byte-for-byte, exactly like `app/tray/single_instance.py`; everything app-specific — the probe, the respawn action, the breadcrumb path, the toast — is a call-site argument. It carries three primitives: `retry_with_backoff`, `HealthWatchdog` (with `rearm()`), and `BreadcrumbLog`.
- **The initial spawn retries with backoff.** A single unretried `manager.start()` at tray boot loses a transient race (port still in `TIME_WAIT`, a cert renewal in flight, a dependency hub not up) and leaves the webapp dead for the tray's whole lifetime. Wire `retry_with_backoff` into the tray's `_start()` on a background thread (so the tray icon still appears while uvicorn boots), and make final exhaustion **loud** — breadcrumb + toast, never a swallowed exception.
- **The watchdog distinguishes dead from wedged, and the caller owns that decision.** `is_port_in_use() == False` → **dead**, safe to auto-respawn (then `rearm()` if the respawn itself failed, or a failed respawn goes silent forever — the watchdog is edge-triggered and a dead process never produces the recovery that would re-arm it). Port bound but `/healthz` silent → **wedged**, **alert only**: auto-killing a stuck process can mask what is actually wrong (`#386` shipped alert-only), which is why the split lives in the caller's `on_wedge`, not inside the vendored class. The probe must be a real `/healthz` round-trip — a port check is exactly what cannot see a wedge.
- **The breadcrumb file is not optional, and it is the piece `logging` cannot replace.** A tray launched by `pythonw` has **no `sys.stderr`**, so `logging.basicConfig()`'s default handler discards the boot-time traceback entirely; redirecting the uvicorn child's `stdout` to `DEVNULL` doesn't help, because the missing record is the *tray's* own. Write a line at every start attempt, retry, wedge, respawn and recovery to `webapp/watchdog.log` (gitignored by the `*.log` rule this scaffold ships). Writes are best-effort and never raise; the file rotates past ~1 MB.
- **Ref:** canonical wiring snippet, dead/wedged table and reasoning: `docs/windows-tray.md` gotcha #5. (`#201`; source instances `photo-ocr#110`, `app-launcher#386`.)

## Restart/deploy coverage — merged is not shipped
*Apply only if this project has more than one long-lived runtime component, or a runtime that lives outside the checkout, such that the project's restart or deploy recipe does not necessarily reach every live thing it owns.*

A merged PR, a green gate, and a successful restart only prove that the *one component the restart step touched* is live. Two failure shapes share the root cause — the finish flow reports "shipped" without observing the actual running target:

- **Out-of-tree runtime.** The code lives here; the thing it changes runs elsewhere — a remote VM, a device, a tailnet peer — and merging changes nothing there until an explicit deploy step runs, even when the repo already owns a working deploy mechanism (`home-automation#314`).
- **In-tree, restart-excluded runtime.** The changed process lives here and normally restarts with everything else — except one component is deliberately excluded from the standard restart for a good reason (protecting live state) invisible from the code alone, so the "verified" restart proves only the *other* component's build sha and the half-restarted state can be worse than either whole version while the API still returns `{"ok": true}` (`app-launcher#611`/`#615`).

**The invariant:** a change must never be reportable as shipped while it is merely merged. Either the flow observed the actual target running the new code, or it says plainly that it did not — and where liveness can't be determined (target unreachable, sha unresolvable), it reports **unknown**, never assumes fine.

**Declare every not-fully-covered runtime component** in this repo's own `CLAUDE.md`, in the same "This repository" section as the restart recipe — one entry per component the standard restart/deploy does not reach:

```markdown
## <component name>
- what/why: <what this component is; why it's excluded from the standard restart, or where it lives if out-of-tree>
- update command: `<the one supported command>` (confirmation-gated if destructive)
- liveness signal: `<field or probe>` — e.g. `GET /api/version`'s `<component>.stale`
- NOT restarted/deployed by: `<the standard restart/finish flow>`
```

**Extend the build-identity endpoint per component, not just per process.** Where `/api/version` already exists (per "Webapp PWA required surfaces"), report a sub-block per not-fully-covered component: `{reachable, git_sha, captured_at, stale}` — `stale` compares that component's own captured identity (captured once, at its own process start/import, via a shared `build_info.py`-style helper — not read live) against the repo's current HEAD sha, and must be `None`/unknown rather than `false` when either side is unresolvable. For an out-of-tree target with no HTTP endpoint of its own, the equivalent is a probe against the target itself (e.g. hitting its live API to confirm a pushed config took effect) — the same "observe the target, not the repo" principle over a different transport.

**Surface the gap at verify time, not just at finish time.** Where a diff-classification mechanism already exists (e.g. `classify_e2e.py`'s path-to-tier routing), reuse its output to print an advisory warning in `verify-before-ship` when the diff touches a declared component's paths, naming the field to check before reporting the change as shipped. Advisory only — it must not fail the gate (the gate can't observe a remote or excluded target).

**The finish flow's obligation:** when a project declares one or more not-covered components and the diff touched their paths, `/issue-finish`-shaped flows check that component's liveness signal after restarting and, if stale or unknown, state so explicitly — "merged but not yet live: `<component>` requires `<the declared manual action>`" — rather than reporting the issue shipped. Where the manual action needs a human (credentials, a physical device, an explicit destructive confirmation), the flow stops and names precisely what's needed rather than closing the issue as done.

**Ref:** the convention + the per-project declaration shape live here; the skill-side enforcement (reading the declaration, checking the liveness field, wording the finish summary) lives in `fleet-config`'s `skills/issue-finish/SKILL.md`. Reference implementation: `app-launcher`'s `src/build_info.py` (shared git-sha + capture-timestamp helper) + `/api/version`'s `session_host` sub-block + `scripts/restart-session-host.ps1` (`-Confirm`-gated, manual-only, never wired into a normal ship flow) + `verify-before-ship.ps1`'s advisory warning reusing `classify_e2e.py`'s routing output (`app-launcher#615`). (`#199`; source instances `home-automation#314`, `app-launcher#611`/`#615`.)

## Multi-repo agent fanout — a dispatched agent works in a worktree, never the primary checkout
*Apply only if this project ships tooling that fans work out across several repos — a scatter-gather skill, a batch runner, a board/scheduler that spawns per-repo agent sessions.*

Global `CLAUDE.md`'s concurrent same-repo rule (first come owns `main`, later sessions build in a worktree) is **claim-based**, and claim-based is exactly wrong for machine-dispatched work: **a running process is not a claim holder**. A live webapp or tray serving the checkout, or a directory junctioned live into an agent's config home, publishes no claim — so a first-and-only dispatched agent *legitimately* wins the primary and edits files out from under the running instance.

- **Worktree-only, unconditionally and uniformly.** Every dispatched per-repo agent builds in an isolated sibling worktree (`<repo>-wt-<N>`, the primary's `.venv` junctioned in) for *every* repo — not "primary unless claimed", and not a per-repo allow-list of which repos currently happen to run something live (wrong the day a repo grows a tray). Interactive human sessions keep claim-or-worktree: one worktree per issue for a single attended session is pure overhead.
- **Enforce it in the tool, not in agent prose — this is the load-bearing part.** A rule an agent must read, recognise as applicable, and *choose* to obey is advisory, and advisory loses. The decision belongs inside the claim helper itself: force worktree mode whenever the explicit flag is passed **or** the dispatch marker is present in the environment, attempting no primary claim and publishing none either way. Keep one documented env escape hatch for the rare dispatched flow that genuinely must hold the primary, with the explicit flag still winning over it. Prose stays as *explanation*; code is the *enforcement*.
- **Teardown is a terminal step of every lane, and residue halts the run.** Each lane ends by recording its outcome (and any WIP sha) on the issue, removing the worktree, releasing the claim, deleting the branch, and confirming the primary is back on a clean default branch. Serialize lanes so at most one worktree exists fleet-wide at any instant, and stop the run on a lane that can't be returned to clean. Post-flight verification enumerates worktrees, sibling `-wt-*` directories, stray branches and dirty trees across *every touched* repo — checking only the merged repos' primaries is what let a run report "0 failed" over 11 strays.
- **Teardown must not assume the happy path.** Strip the `.venv` junction *before* removing the tree on every path including the fallback (a reparse point walked by a recursive delete is the classic footgun); don't derive the primary by `rev-parse` from *inside* the worktree, since git deregisters it while the directory survives and that call then exits non-zero; and exit non-zero naming the surviving path rather than reporting a false clean.
- **A live-e2e guard refusal is a hard stop for a dispatched agent.** Per the e2e live-instance guard above, the opt-in env var represents an attended human decision about a live app. An unattended fanout agent that hits the refusal reports it and stops; it never sets the flag to get past it.
- **Pin the mandate with an executable guard.** The rule is load-bearing prose spread across several dispatch paths, so a context purge or a well-meant rewrite can drop it silently. An acceptance test asserting the mandate is present in each dispatch path *and* in the claim helper's own implementation is what keeps it from evaporating.

**Ref:** the convention lives here; the implementation — the claim/worktree helper and the dispatch paths that call it — lives in `fleet-config` (`skills/_lib/worktree_claim.py`'s `acquire --force-worktree` plus its `APP_LAUNCHER_SESSION_ID` environment trigger and `WORKTREE_CLAIM_ALLOW_PRIMARY` escape hatch). (`#202`; source instances `fleet-config#515`/`#518`/`#522`/`#525`/`#526`/`#527`/`#528`.)

---

## This repository
<!-- Replaced per repo. Keep to two sentences max. -->
<one sentence: what this project is>.
See `README.md` for setup, layout, and usage.
