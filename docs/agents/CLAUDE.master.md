# Project Instructions

Canonical AI-agent instructions; Claude Code reads as project memory, other agents (Cursor, Codex, …) via the one-line `AGENTS.md` pointer.

> **Scope — project-shaped guidance only.** Only project-shape-specific guidance (Streamlit, GitHub-Actions CI, e2e UI testing, tray/long-lived process) lives here, each section gated *"apply only if…"*. Universal dev-workflow directives (plan mode, asking, editing, git, PR pipeline, docs discipline, senior-dev check) live once in `fleet-config/global-CLAUDE.md` (→ `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`), not here. Test: *"would it apply to a bare repo with no app?"* Yes → global; no → here; never both — `/context-audit` enforces weekly (`project-scaffolding#68`).

Conventions:
- Issue refs are `project-scaffolding` unless another repo named.
- ***(PWA)*** in a heading = *apply only if this project serves a FastAPI + static PWA web app; Streamlit POC spikes are exempt*. Other gates spelled out under their own heading.
- **Don't diverge, don't re-author.** Every convention/vendored component/token contract here is owned here: fix in this scaffold, re-vendor downstream, never fork in a consuming app. Each section closes with reference docs + decision record.

## Agent config artifacts (instructions and scoped project skills)
*Apply when adopting this scaffold's agent configuration layout.*

- **`AGENTS.md` is a committed short pointer to `CLAUDE.md`, never a copy.** Keep the instruction chain; machine-scope policy owned by `fleet-config`.
- **One source per project skill.** Keep existing sources; discover native compatibility before adding a per-skill junction/symlink at the same repo/package scope. Never broaden a nested skill into a root or user-global catalog. Preserve real `.agents` directories; report name/target collisions without overwriting.
- **Agent directories are ignored by default, not disposable noise.** `.claude/`, `.agents/`, `.codex/`, `.pi/`, `.grok/` may hold private context or owned discovery artifacts. Only deliberately shared skill sources get narrow ignore exceptions; generated links, local settings, conversations stay ignored. Fresh clones/worktrees recreate own links to own sources.
- **Adoption/proof:** follow [portable project skills](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/agents/project-skills.md) contract — scope, helper exclusions, collisions, ignore allowlists, native discovery checks. Installer mechanics belong to `fleet-config`, not a per-project fork. (`#28`, `#250`.)

## Streamlit conventions
*Apply only if this project uses Streamlit.*

- `st.set_page_config(layout="wide", page_title="...")` MUST be the first Streamlit call.
- Use `width="stretch"`/`width="content"`. **Never** introduce new `use_container_width=True` (deprecated); migrate existing uses when touched.
- All mutable state in `st.session_state`; no module-level globals.
- `@st.cache_data` for DataFrames/files; `@st.cache_resource` for DB clients/models.
- Every widget needs a stable, explicit `key=`.
- UI code only in the UI directory (e.g. `app/`); data logic in the non-UI package (e.g. `src/`). Never import `streamlit` from non-UI code.
- User feedback via `st.error()`/`st.warning()`/`st.success()`, not `st.write()`.
- **App layout:** main file (e.g. `app.py`) handles only page config, shared state, sidebar, routing. Default to native multipage nav — `st.navigation` + `st.Page`, one view per file exposing `render()`. `st.tabs()` for sub-sections *within* a view; sidebar radio only when asked.
- **Ask before assuming:** `st.session_state` key names/scope; caching strategy (`@st.cache_data` TTL vs `@st.cache_resource`); widget `key=` names/input sources; page placement (new page vs section in existing).
- **Custom CSS/JS hooking Streamlit's internal DOM is fragile** — raw `data-testid` selectors undocumented, rename between versions; `position: sticky` inside `st.container(key=...)` breaks on Streamlit's per-element `stLayoutWrapper` divs. Fix: `docs/streamlit-css-hooking-gotchas.md`.

## Web-app visual identity (fleet design system) *(PWA)*

Fleet web app inherits look **and** navigation; re-authors neither. `fleet-config` owns the *spec* (`design.md` + `design.dark.md`, junctioned into `~/.claude`, plus `/design-sync`); this scaffold owns the *vendored implementation* (`app/webapp/static/_vendored/`).

- **Tokens come from the spec, not you.** Wire CSS custom properties (`:root`/`[data-theme]`) to `~/.claude/design.md` (light) + `~/.claude/design.dark.md` (dark) — colors, typography, spacing, radii. **Don't** copy spec into repo; **don't** invent a second accent/per-app palette. `/design-sync` reports drift.
- **Nav is vendored, not re-implemented.** Floating bottom-tab pill (desktop segmented control → mobile pill — fleet *navigation contract*) comes from `app/webapp/static/_vendored/nav/` (`nav-tabs.js`+`nav-tabs.css`+`nav-tabs.html`). Copy folder **verbatim**; adapt only markup (which tabs) and `storageKey`. Nav markup must be a direct `<body>` child, sibling of `<main class="app">`, **never** nested inside content wrapper/scroller — iOS anchors fixed-position descendants of scrollers to short-tab content instead of viewport (`home-automation#232`). Same "copy byte-for-byte, never fork per-app" rule as tray's `single_instance.py`.
- **`_vendored/` is the UI component channel.** New shared HTML/CSS/JS components live under `app/webapp/static/_vendored/<component>/`, normalized from best fleet implementation. Don't hand-copy a sibling app's snippet — vendor from here. Convention + how to add one: `app/webapp/static/_vendored/README.md`. (`#79`; aligns to `fleet-config#178`.)
## UX surface — diff-keyed design-conformance gate *(PWA)*

Diff-keyed gate at finish: checks the touched web UI still conforms to the design spec and isn't visually broken. Distinct from the periodic fleet-wide audit (`fleet-config#180`) — this is the don't-introduce-new-drift arm.

**Two checks, kept separate — a real gate uses both, scoped to the diff.** *Token check* (`/design-sync`-style): diffs CSS custom properties (light+dark) and the nav contract vs spec; static, no browser, never renders — catches "accent drifted", misses "nav pushed off-screen / cards overlap". *Visual verification* (`verify`-style): launches the live app, drives the touched view in a headed browser, screenshots it — the only check that *sees* the result; the token-expensive leg.

**Each project declares a `## UX surface` block in its own CLAUDE.md** (per-project instance the skills read, like `## CI expectations`) — don't inline paths into the skill. This scaffold ships the block below as a *live* declaration, not a fenced sample: enabling the gate is a one-word edit (`design spec applies` → `yes`, then adapt paths/views). `ux_surface.py` tolerates a descriptive `— …` suffix on this heading but matches only the first `## UX surface` heading — never add a second.

**The live block for this repo** — edit these lines in place; the skills read exactly them:

- design spec applies: no        # flip to `yes` once this repo serves a FastAPI + static PWA; `no` = gate no-ops
- paths:
  - app/webapp/static/**/*.css
  - app/webapp/templates/**
  - app/webapp/static/**/*.{js,html}
- key views:                     # used only by the `ux-full` whole-app sweep
  - /          (home + bottom nav)
  - /settings

**The gate contract (shared skill behavior):**
- **Deterministic, diff-keyed — not per-run LLM judgment.** Trigger: does `git diff <main>...HEAD` intersect the declared `paths`? Yes → run; No → skip and state it in the finish summary (`no UX surface touched`). Same mechanism as `## CI expectations`'s e2e-surface skip.
- **Cheap design-aware load at `/issue-start`**: if the picked issue is likely to touch the UX surface, read `~/.claude/design.md` + `design.dark.md` before building (two file reads, no browser) — no `/design-sync`, no screenshot at start.
- **Gate at `/issue-finish` (and `/issue-yolo`), only when the diff touched the surface** — two legs:
  - **Token check, fix-now semantics.** Compare touched UX files (CSS custom properties light+dark + nav contract) to spec and fix material drift in this branch before merge — unlike vanilla `/design-sync`, which files-and-defers a `design-drift` issue for the periodic sweep.
  - **One screenshot** of the touched view via the `verify` skill, attached to the PR body. Diff-scoped, never a whole-app sweep by default.
- **Manual overrides** (mirroring `/issue-start`'s `now`/`plan`): `ux`/`design` forces the gate even if the diff looks code-only; `no-ux` skips it when the detector over-fires; `ux-full` audits the whole app's `key views` — the one expensive path, opt-in only.
- **Materiality bar** (from `/design-sync`): a 1-unit radius/spacing nitpick is not a blocker; a wrong canvas color, missing dark theme, hand-rolled nav, or visibly broken layout is.
- **Keep-the-human-in-control.** Always state the gate decision (ran/skipped/`ux-full`, plus any drift fixed) in the finish summary, so the user can veto.

**Where each piece lives:** convention + block default here; skill mechanism in `fleet-config` `skills/issue-{start,finish,yolo}/SKILL.md` (`fleet-config#195`); per-project instances in each project's own block; periodic fleet-wide drift sweep is separate (`fleet-config#180`). Browser screenshots must go through the `verify` skill's stealth-Chrome launch (real Chrome, no automation infobar, per global `CLAUDE.md`) — never re-inline launch args. (`#83`.)

## HTTPS provisioning *(PWA)*

An installed PWA needs HTTPS (Service Workers + Web Push are HTTPS-only); which path to take depends on how the app is reached remotely.

- **Reached over Tailscale → `tailscale cert` (preferred).** Provision a real Let's Encrypt leaf for the tailnet MagicDNS name with `scripts/gen_tailscale_cert.py`. Tailscale owns `ts.net` and answers the ACME DNS-01 challenge: no public DNS name, no HTTP-01/DNS-01 setup, no inbound exposure, zero per-device trust steps. One-time prereq: enable HTTPS in the tailnet admin console (DNS → HTTPS Certificates), once per tailnet.
- **Auto-renew on startup is mandatory.** LE leaf is ~90 days (vs a self-signed root's 10 years) — manual re-issue will be forgotten. `gen_tailscale_cert.py --check` renews only a `.ts.net` cert expiring within ~30 days, no-ops a self-signed cert, never blocks startup on error. Wire `--check` into the app's own webapp launcher (e.g. `webapp.bat`), before uvicorn binds — not the generic `tray.bat.template` (cert provisioning is app-specific). Reference: `grocery-shopping-automation`'s `webapp.bat`.
- **LAN-only / no Tailscale → self-signed CA (fallback).** Keep the self-signed CA + leaf (`gen_ssl_cert.py`) and the per-device trust dance (`certutil -user -addstore Root ca.pem` + full-Chrome-restart gotcha; iOS `/install-ca` `.mobileconfig` + Certificate-Trust toggle). Correct only with no tailnet. The in-app `/install-ca` Settings affordance (`#74`) is scoped to this fallback — a `tailscale cert` app does not ship it.
- **Ref:** full procedure (commands, admin-console step, iPhone install): `docs/app-onboarding.md` §2–§3. (`#89`.)

## Webapp PWA required surfaces (build-identity footer + Settings/CA-install) *(PWA)*

- **Build-identity footer — `GET /api/version` → `{git_sha, built_at}`.** Capture values once at module load via a hardened `git rev-parse --short HEAD` (`git -C <project-root>`, `stdin=subprocess.DEVNULL` + `creationflags=CREATE_NO_WINDOW`), and render `Build: <sha> · <ts>` as a plain `<p>` outside every card. A `/healthz` 200 passes on a stale process, a matching `git_sha` does not — the `/issue-finish` + `/issue-yolo` tray-restart verification depends on this endpoint existing. Auth-gated (loopback bypasses; the PWA attaches the bearer via the page's `jsonApi`) so a build SHA is never exposed to an unauthenticated remote caller. Universal — present regardless of how HTTPS is provisioned.
- **Settings block** — a collapsible `⚙️ Settings` `<details>` with an Install-certificate link to `/install-ca` (route serving the iOS `.mobileconfig`). `/install-ca` is auth-exempt, so the link is a plain `<a href>` navigation working over Tailscale without a token — not a `jsonApi` fetch. Include a short iOS trust how-to beside it. The block's app-specific contents (config fields, passkey/WebAuthn, tunnel status) are not part of the standard — only the collapsible block + CA-install affordance are.
- **The CA-install link is conditional on the HTTPS path (ties to `#89`).** Ships only on the self-signed/LAN-only fallback; a `tailscale cert` app omits or hides it. The `/api/version` footer stays regardless.
- **Ref:** the scaffold ships no starter FastAPI server, so this is documented, not seeded — a vendored `_vendored/settings/` component is a future step (`app/webapp/static/_vendored/README.md`). Reference: `app-launcher` `app/webapp/routers/misc.py` + `static/{index.html,main.js}`, and `home-automation`. (`#74`.)

## Webapp PWA static-asset cache-busting (`CachingStaticFiles` + fleet hash) *(PWA)*

iOS Safari — installed home-screen PWAs especially — heuristic-caches static assets served by a bare Starlette `StaticFiles` mount (only `ETag`/`Last-Modified`, no explicit `Cache-Control`): after a deploy + tray restart the device runs the old cached JS/CSS while `/api/version` reports the new build. Every fleet PWA ships the same fix — a required convention, not an optional extra.

- **One canonical reference, copied — not re-derived.** `home-automation/src/static_versioning.py` plus the `CachingStaticFiles(StaticFiles)` subclass (`home-automation/app/webapp/server.py`); adapt nothing but the static dir. Canonical names: `BuildInfo.stamp_html` / `stamp_js` (wrapping `rewrite_index_html` / `rewrite_js_imports`).
- **Fleet hash, not a naive per-file hash.** The webapp is an ES-module graph (`index.html` → `main.js` → imports), so a per-file hash goes stale on transitive edits (`state.js` changes, `main.js`'s bytes don't). Use one fleet hash = a single SHA-256 over the concatenation of every hashable file's per-file hash; any edit to any module rotates every `?v=` stamp.
- **Stamp idempotently, degrade gracefully.** The import/href regexes also capture an existing `?v=…` and replace it, so re-stamping an already-served body is safe; an unreadable static dir or missing file falls back to unstamped URLs rather than crashing the page.
- **Per-suffix `Cache-Control`; the shell always revalidates.** `.js`/`.css` get `public, max-age=31536000, immutable` (safe because the fleet hash is the cache key); manifest/icons get `public, max-age=86400`. The shell (`index.html` root route) is served `Cache-Control: no-cache, must-revalidate` — otherwise a cached shell still points at the old entry module and the hashing buys nothing.
- **Ref:** reference snippet `docs/app-onboarding.md` §4. Service workers/offline caching are deliberately not used in the fleet. (`#78`.)

## Windows event-loop pinning (uvicorn) *(PWA)*

- Every uvicorn spawn point (tray subprocess spawn via `manager.py`, a programmatic `uvicorn.run()`, `.bat` launcher scripts, e2e autoboot spawns) must pass a pinned selector-loop factory (`--loop`/`loop=`) — asyncio's default Windows proactor loop wedges the listening socket on any aborted client connection (`app-launcher#388`). Worked shim: `docs/app-onboarding.md` §1; reference implementation: `app-launcher`'s `app/webapp/event_loop.py` (`selector_loop_factory`).
## Windows console-subprocess suppression (`CREATE_NO_WINDOW`)
*Apply only if this project runs a long-lived Windows process (tray, daemon, GUI) without its own console — e.g. launched via `pythonw` — that shells out to a console-based CLI tool (`docker`, `nvidia-smi`, `git`, `taskkill`, …).*

- Every console-tool subprocess call (`subprocess.run`/`subprocess.Popen`, `asyncio.create_subprocess_exec`) must pass `creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0` — else Windows flashes a fresh console per child (`#13`). Centralize behind one helper, not inline literals; `asyncio.create_subprocess_exec` takes the same flag and is easy to miss. Helper lives in the project's non-UI package; this scaffold ships `src/no_window.py`, imported as `from src.no_window import NO_WINDOW` (`#209`).
- **Vendor-verbatim modules are the one exception, not drift.** Files copied byte-identical into adopters (this scaffold's `$VendoredModules` list in `scripts/verify-before-ship.ps1` — e.g. `tests/e2e/_browser_sweep.py`, `scripts/classify_e2e.py`) can't import the shared helper (wouldn't resolve in consumer tree; hash-verified bytes must stay self-contained) — they derive the flag locally on purpose with a comment saying so. Don't "fix" into an import; don't count in audits.
- A standalone entry point (`scripts/` CLI, subprocess-launched test helper) has its own dir as `sys.path[0]`, not repo root — needs `sys.path.insert(0, <repo root>)` before the import. Keep the shared helper stdlib-only, side-effect-free, safe under a stripped venv.
- **Never add `DETACHED_PROCESS` on top — it neither suppresses the window nor escapes a subtree kill.** Measured from a console-less `pythonw` parent (`#221`): bare `CREATE_NO_WINDOW` suppressed every run; `DETACHED_PROCESS` alone, `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, and `CREATE_NO_WINDOW | DETACHED_PROCESS` **each** showed a visible window. Mutually exclusive per `global-CLAUDE.md`/`local-llm-hub#282` — defer to it. Keeping a long-lived child alive across tray teardown is a **re-parenting** problem, not a creation-flag one: `taskkill /T` walks the PID tree regardless — use `cmd /c start` re-parenting.
- Trap: a `pythonw` child launched without redirected `stdout`/`stderr` crashes on its first log write — always give it a real target.
- Worked helper: `docs/app-onboarding.md` §1.

## FastAPI + SQLite connection lifecycle (one `get_db` `Depends` dependency)
*Apply only if this project is a FastAPI app backed by SQLite.*

- **One dependency owns the connection.** `get_db()` connects, sets `row_factory = sqlite3.Row` + `PRAGMA journal_mode=WAL`, then `try: yield / finally: conn.close()`. Handlers take `db: sqlite3.Connection = Depends(get_db)` rather than opening their own — closes even on handler raise, and setup (pragmas, row factory, timeout) can't drift between handlers. Acceptance: zero per-handler `sqlite3.connect(...)` calls in routers.
- **SQLite + stdlib `sqlite3` stays the fleet default.** Convention covers only the *lifecycle dependency* — no ORM, no async driver, no connection pooling. (Apps legitimately needing a long-lived single connection are the documented exception.)
- **Ref:** canonical `get_db` + `Depends` snippet: `docs/app-onboarding.md` §4. (`#96`; source instance `whatsapp-radar#100`.)

## Outbound-connection discipline (pooled sessions, backoff, bounded fan-out, no leaked children)
*Apply only if this project runs a long-lived process (tray, daemon, webapp, poll loop) that makes outbound HTTP/TCP calls — to another local app, an external API, or hardware.*

Windows ephemeral-port exhaustion (global `CLAUDE.md`; `fleet-config#440`) makes a fresh-connection-per-call poller a whole-machine outage risk, not a local inefficiency.

- **Reuse connections — `/propagate-vendored` component: `src/pooled_http.py` (manifest key `pooled_http`).** A bare `requests.get`/`requests.post` inside a poll loop, health check, or per-item fan-out is a **defect**: fresh connection + fresh `TIME_WAIT` port every call. `build_session(pool_size)` returns a `requests.Session` with a sized, keep-alive `HTTPAdapter` mounted on both schemes, built once (e.g. module import), never reconfigured per call; `pooled_request(method, url, *, timeout, session=SESSION, **kwargs)` dispatches through it and retries **once** on `requests.exceptions.ConnectionError` — safe even for non-idempotent methods, since the failed attempt never reached the server. Reference: `app-launcher#605`'s `src/_loopback_http.py`. `requests` is **not** added to every scaffolded project's `requirements.txt`; only this repo's own copy (proven via its unit tests) declares it.
- **Back off what is failing — prose only, no vendored helper yet.** Failures escalate the retry interval, success recovers it. No proven implementation to vendor from (`home-automation#537` still open); extract a shared tracker once a real fix lands.
- **Cap the fan-out — prose only.** Bound concurrency (`asyncio.Semaphore(N)` around the poll loop) rather than firing all N every tick. Inline at the poll loop — too thin/framework-specific to vendor.
- **Do not leak child processes — the sweep ships: `tests/e2e/_browser_sweep.py` (`#203`).** An e2e suite must close every browser/context it opens, including on a failed/interrupted run (`finally`/fixture-teardown, not just happy path). The `pytest_sessionfinish` sweep **classifies before it kills** — requires all three: really running, parent dead, and cwd under the checkout this run owns. Blanket kill-by-image-name stays **forbidden** (would take down another session's run, or the user's own Chrome — why Chromium is deliberately excluded). Three findings must survive any rewrite:
  - **An exit code is not an exit** (`#236`). A genuinely-exited helper is not a leak (Windows keeps its process object/`tasklist`/WMI row alive while any handle remains — unkillable but harmless); a helper whose exit code is set while `GetProcessTimes` reports **no exit time** is *wedged inside termination* — unkillable yet still holding its cwd, the state that pins a checkout against deletion. Liveness is a tri-state plus unknown, never a bool; a wedge gets its own cwd read + verdict instead of being swallowed as a zombie.
  - **Anything the sweep can't establish** (unreadable cwd, unresolvable liveness, non-Windows host) reports its own **unknown** verdict, never folded into "clean".
  - **Reclassifying is not fixing.** Nothing can reap a wedge, so the e2e conftest starts the Playwright driver from a neutral cwd (`gettempdir()`, never `mkdtemp()`) and every spawned helper roots in `%TEMP%` instead of the checkout; a pinned directory is freed by closing the holder's cwd handle remotely, never by rebooting the host.
  - Full pattern, abort-cascade matrix, liveness discriminator, PEB cwd-attribution trick: `docs/playwright-ui-testing.md` → "Post-run sweep for leaked browser helpers".

## Runtime data lives on a fast drive, not wherever the repo was cloned
*Apply only if this project persists SQLite (or similar fsync-heavy state) from a long-lived process.*

- **Resolve the path — `/propagate-vendored` component: `src/runtime_data.py` (manifest key `runtime_data`).** `runtime_db_path(app, filename, env_var=...)` returns `<root>/<app>/<filename>`; root = `FLEET_DATA_ROOT` → else `C:\sqlite` (Windows) / `$XDG_DATA_HOME/sqlite`. One subdirectory **per app**, so two apps can both own a `telemetry.sqlite3`. A repo-relative `Path(__file__).parent.parent / "webapp" / "x.sqlite3"` is a **defect** — it ties the physical drive to where someone cloned.
- **Change the path; never junction it.** A junction migrates data with no code change and records nothing — undrivable by tests, invisible to a reader, walked by any recursive delete.
- **Keep the app's existing full-path override** (`TELEMETRY_DB_PATH`, `WR_DB_PATH`, …) as highest precedence — pass as `env_var=`. Every unit/e2e harness sets it; outrank it and a test run writes into the live store.
- **Outside the git tree is outside git-derived backup.** `fleet-config`'s `backup_private.py` backs up the `C:\sqlite` root as an explicit source; an app inventing its own root elsewhere is unbacked.
- **Why:** seven always-on services `fsync`ing to the drive their checkouts sat on kept a spinning HDD audibly clicking around the clock (`#243`, diagnosed on `tower`; drive itself measured healthy).
## GitHub Actions CI conventions
*Apply whenever this project adds a `.github/workflows/` file.*

- **Pin a dated Windows runner:** `runs-on: windows-2025`, never `windows-latest` (GitHub redirects `windows-latest`→`windows-2025`, deadline June 2026) — an OS image change must not silently flip a green gate red.
- **Use Node-24 action majors:** `actions/checkout@v6`, `actions/setup-python@v6`, `actions/upload-artifact@v7` — not `checkout@v4` / `setup-python@v5` / `upload-artifact@v4` (deprecated Node 20; forced Node 24 from June 16 2026, Node 20 removed September 16 2026). Drop-in, inputs unchanged.
- **Trigger once per commit: `push:[main]` + `pull_request:[main]`.** Do **not** trigger `push` on feature branches (no `branches:` filter, or `branches-ignore:[main]`): with a PR open both events fire and the gate runs **twice on the same commit**; `branches-ignore:[main]` also *omits* the post-merge `main` gate. `concurrency` can't fix it (`github.ref` differs: `refs/heads/<branch>` vs `refs/pull/<N>/merge`). Non-loss: CI on a branch pushed but never PR'd — `/issue-finish` always pushes then immediately opens the PR.
- **Run counts, wrong shape → this convention:** feature-branch push with open PR **2→1**; no PR yet **1→0** (open the PR before you need CI); merge commit on `main` **0→1**.

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

**Sister-repo tracking:** a repo still on the old runner/actions (`#25`) or duplicate `push`-on-branches trigger (`#38`) gets a pointer issue back to `project-scaffolding`'s canonical record. Fix before the deprecation deadline.

**A red default branch files its own tracking issue — `main-gate-watch`.** Copy `.github/workflows/main-gate-watch.yml.template` → `.github/workflows/main-gate-watch.yml`, replace `__GATE_WORKFLOW_NAME__` with the gate workflow's `name:`. On `workflow_run` completion for that workflow (filtered `branches:[main]`, PR runs excluded, gated on `conclusion=='failure'`): creates label `ci-red-main` (`--force`, idempotent), comments `Still red on main at <sha>: <run-url>` on the open `ci-red-main` issue, or files `main's <gate> gate is red` (`bug`+`ci-red-main`, assigned to `github.repository_owner`) if none open. Issue stays open until `main` is green; discounting a red gate for an unrelated PR does not close it. Without this, a red `main` is nobody's finding (`whatsapp-radar#258`; three repos found red same day, 2026-08-15).

- **Precondition:** a `workflow_run` watcher can only observe a gate that runs in Actions on pushes to the default branch. A repo whose gate is local-only (`verify-before-ship.ps1`/`pytest` on-machine — *this scaffold included*) gets **zero** coverage — don't install the watcher there. Its red-`main` detection is **unknown**, reported as its own state, never folded into green.
- **Local-gate repos get a scheduled fleet-side sweep instead, not an advisory Actions gate** (`#222`) — a ported Windows-desktop gate on a hosted runner is a degraded subset, and a green watcher over it is false coverage. So: watcher where Actions runs the real gate; scheduled sweep of the actual local gate elsewhere — both file the same idempotent `ci-red-main` issue; a gate that can't run reports `unknown` with a reason. Sweep belongs in `fleet-config` as its own scheduled skill (not bolted onto `/audit-fleet`, whose bounded weekly cost depends on no per-repo workloads); **unbuilt** — until it exists, local-gate repos have no automated detection and should say so.

## CI is advisory — `## CI expectations` block + e2e-surface skip rule
*Apply whenever this project has a `.github/workflows/` file **and** a local verification gate.*

**CI is advisory, not a required gate.** Fleet e2e workflows run on repos with **no branch protection**, so checks aren't required to merge; the **local gate** (`scripts/verify-before-ship.ps1`, or `pytest + ruff + mypy`) is the contract. Never treat `gh pr checks --watch` as a mandatory blocking wall.

**CI's only signal beyond the local gate is the e2e suite** — the local gate runs `pytest + ruff + mypy` but skips the Playwright leg (needs browsers + live webapp; also the known-flaky part on the slower hosted Windows runner). A diff touching **none** of the project's e2e surface gains nothing from waiting on CI; a wedged WebKit browser can block the merge up to `timeout-minutes`.

**Each project declares a `## CI expectations` block in its own `CLAUDE.md`** (per-project instance: durations, flaky leg, e2e-surface paths). `/issue-finish` reads it; don't inline these values into the skill. Template (fill bracketed values):

```markdown
## CI expectations
- Workflow `[.github/workflows/e2e.yml]`, job `[verify-before-ship]`, on every PR. **Advisory, not required** (no branch protection) — the local gate is the contract.
- Typical green: **~[N] min**. Investigate at **>[2N] min**; treat as wedged at **>[~4N] min**.
- Flaky leg: `[the Playwright WebKit/iPhone projection / PTY-input tests]` can wedge on the hosted runner. `timeout-minutes: [30]` caps a wedge. A wedge is a flake, not the diff.
- CI's only signal beyond the local gate is the **e2e suite** (skipped locally). Its e2e surface = `[app/webapp/, app/tray/, tests/e2e/, static assets, …]`. A diff touching **none** of these gains nothing from CI.
```

**What `/issue-finish` does with it:**
- **Skip-the-wait keyed on e2e surface, not "docs vs code."** No declared e2e surface touched + local gate green → merge on local-green and **state it** in the finish summary (e.g. `CI not awaited — store-only diff, no e2e surface touched`). Generalizes the old `*.md`-only skip rule.
- **Proactive flake handling.** Read expected duration from the block; at the *investigate* threshold, inspect the run (`gh run view --job`), classify flake vs real failure; for the *documented* flaky leg, cancel + rerun **once** automatically, stating so. Second flake → stop, surface to user. **Never** rerun a real failure.
- **Keep-the-human-in-control.** Always **state** the CI decision (skip/wait, any rerun) in the finish summary. Auto-rerun capped at **once**, only for the documented flaky leg. No force-merge; CI advisory means no `--admin` needed. **If a repo later makes `e2e` a *required* status check, fall back to watching** — a required check can't be skipped without `--admin` (out of scope).

**Where each piece lives:** convention + block template here; skill mechanism in `fleet-config` `skills/issue-finish/SKILL.md` step 5; per-project instances in each project's block; sister-repo pointer issues (start: `whatsapp-radar`, `app-launcher`) track adoption. Fixing the e2e leg's flakiness is a separate per-project task — this convention makes a flake cheap, not cured.

## Diff-proportionate e2e routing (`.fleet.toml` `[e2e]` + `classify_e2e.py`)
*Apply only if this project has a browser e2e suite (`tests/e2e/`) wired into `verify-before-ship.*`.*

Makes the local gate's browser phase proportionate to the diff instead of running all of `tests/e2e` every change. Proven in `app-launcher` (`scripts/classify_e2e.py`, `#568`/PR `#574`), promoted here parameterized.

- **Mechanism shared, rules declared per-project.** `scripts/classify_e2e.py` reads an `[e2e]` table from the repo's own `.fleet.toml` (paths→tier map). TOML so stdlib `tomllib` loads it with zero custom parsing, rules versioned beside the code they classify. `.fleet.toml` is the single auditable home for the routing table.
- **Three tiers, worst-wins across the diff:** `skip` (every changed path declared `none` — backend/docs/tooling) — no browser suite runs; `static` (worst path declared `static` inert asset) → narrow `static_pytest_target`; `full` (any `full` path, any unmatched path, empty diff, or no usable `[e2e]` table) → whole `full_pytest_target`.
- **Fail-safe is the point — uncertainty escalates, never narrows.** Unrecognized path, mixed diff, malformed/absent table all route to `full`. The table can only shrink an already-recognized-narrow diff, never a matched change further. CSS/JS route to `full` (no curated "layout subset" — drift-prone, under-testing risk); `static` stays to genuinely inert types (images, fonts, inert vendored HTML fragments). Rules are first-match-wins — declare specific `static` rules before the broader `full` prefix they sit under.
- **Wiring:** `verify-before-ship.*` runs byte-compile + non-e2e pytest **unconditionally**, then routes **only** the browser phase on the classifier's `E2E_TIER`. On CI (`$env:CI`) routing is bypassed, full suite always runs.
- **Anti-drift guard mandatory — two required:** the `unclassified→full` fail-safe, **and** `tests/test_classify_e2e.py` loading the real `.fleet.toml` and asserting representative paths land in their intended tier. New e2e-relevant directory → add its `full` rule to `.fleet.toml` **and** a representative assertion to that test **in the same PR** (same anti-staleness contract as `.fleet.toml` `description` and `docs/architecture.mmd`).
- **Ref:** full schema/rule-writing: `docs/e2e-routing.md`. Web-app-shaped adopters (grocery, whatsapp-radar, family-accounting, mathgamesforkids, life-os, website, home-automation) get one-line pointer issues for follow-on adoption — not scoped here. (`#180`; source instance `app-launcher#568`.)
## End-to-end UI testing
*Apply only if this project serves a browser UI (Streamlit, FastAPI, Flask, etc.).*

Two loops, kept separate. Full setup/bootstrap recipe: `docs/playwright-ui-testing.md`.

### Iterative verification (headed, agent-driven)
- Drive the running app via **Playwright MCP server in `--headed` mode** (Claude Code, Codex CLI); no MCP support → small `playwright` Python script via Bash, `headless=False`.
- Boot the app **once** on a fixed port (Streamlit default 8501), leave it running. Don't restart between iterations unless `set_page_config` or top-level imports changed.
- Prefer a11y `snapshot` over `screenshot` (DOM cheaper than pixels in tokens). Screenshot only on failure or final visual confirmation.
- Cap ≤5 actions per cycle, then report. Stop and ask if page state is unexpected — don't loop blindly.
- Target widgets via stable `key=` using `page.get_by_role(..., name=...)` or `page.get_by_test_id(...)`.
- Do NOT create files under `tests/e2e/` for verification — throwaway, conversation-only. Promotion to a permanent test is a separate, deliberate decision.

### Regression suite (headless, pytest-playwright)
Optional, lives at `tests/e2e/`. Don't create the folder until the first regression test is actually justified.

- Add a test only when all three hold: (1) silent breakage would hurt, (2) can't be caught by a unit test under `tests/`, (3) behavior has stabilized.
- Run via `& .\.venv\Scripts\python.exe -m pytest tests/e2e/` (Windows) / `./.venv/bin/python -m pytest tests/e2e/` (POSIX). No LLM in the loop, zero per-run cost.
- One shared session fixture boots the app plus any service dependencies (API process, worker, PTY host, …) once per pytest run. Engine-agnostic: `streamlit run`, `uvicorn`, `flask run` are all just the launch command.
- Default to isolation: boot a disposable instance; if target port occupied with no opt-in, **refuse** (`pytest.exit`, naming the flag) rather than killing/reusing what's there. Bare `pytest tests/e2e` must never silently drive a live app the harness didn't start (`#191`).
- Opt-in to *acting on* an occupied port = one loudly-named env var per project (`LAUNCHER_E2E_LIVE`; scaffold's `STREAMLIT_E2E_LIVE`) — never an opt-**out** flag (e.g. `E2E_FORCE_AUTOBOOT=1` has backwards polarity: forgetting to set it silently re-enables adoption).
- What the flag permits differs per repo — don't conflate: `app-launcher`'s `LAUNCHER_E2E_LIVE` = read-only assertions against the live tray, never a kill (`_require_live_tray` guard; `--e2e-autoboot` never adopts the live session-host on `:8446`, always spawns its own on a free port). This scaffold's `STREAMLIT_E2E_LIVE` = kill-and-restart via `ensure_fresh_streamlit`, legitimate only because the target is a stateless, cheap-to-restart dev server *and* goes through this repo's own canonical restart helper, never a by-hand kill (`#197`). A repo adopting the vendored guard picks its own meaning, documented in the guard's exit message pointing at that repo's CLAUDE.md. **Log** which instance (disposable vs acted-on-live) the suite is driving and why, so a hung run is diagnosable from its own output.
- Isolate anything stateful — never adopt-and-mutate a host holding the user's live work, even under the live opt-in. The reclaim-on-opt-in rule is safe only for a stateless, cheap-to-restart webapp. A host owning user state or child processes (session-host, worker with in-flight jobs, PTY host) must **always** get the harness's own disposable instance on a free port, injected via env override — never the live fixed port, opt-in or not. Litmus test: is the thing I'd be touching holding work the user would be upset to lose? If yes, isolate unconditionally. Same bar — a destructive test scopes to what it created: snapshot pre-existing ids before acting, kill only the delta, never `.first`/"whatever's in the list" (`app-launcher#260`).
- Is a `/propagate-vendored` component: `tests/e2e/_e2e_live_guard.py` (manifest key `e2e_live_guard`). The policy — check target port, refuse (`pytest.exit`, naming the flag) if occupied with no opt-in, else log the decision — is shape-independent; only the port number, flag name, and how the disposable instance boots are call-site parameters (`#191` shipped it prose-only; `#194` reversed that). Same vendoring pattern as `app/tray/single_instance.py` and `tests/e2e/_geometry.py`: copy the file byte-identical into an app's `tests/e2e/`, call `require_disposable_instance(port, flag_env_name)` from the fixture, let `/propagate-vendored e2e_live_guard` hash-verify and re-vendor fleet-wide. (`tray_lifecycle.ps1` is NOT a valid precedent — de-vendored in `#153`.) Adopter records the entry in its own `.fleet.toml`'s `[vendored]` table — never here.
- Boot failure is a hard failure — never `pytest.skip`. A suite that skips when the app isn't up reports green on a build it never tested. Skip is fine for the ad-hoc "use whatever tray I have running" path; the pre-ship path must fail loud.
- Keep the suite small — target < 15 tests total. Tempted to add #20 → delete two first.
- No Page Object Model. Too much ceremony for this size.
- Don't gate commits on e2e. Run on push or in CI, not in pre-commit.
- When you remove a feature, remove its e2e test in the same commit.

### Mobile / phone-first UI testing
*Apply only if the app's primary surface is a phone.*

- Project the regression suite onto **WebKit** with a device-emulation descriptor (Playwright ships iPhone/Android descriptors — viewport, user-agent, touch, scale factor). WebKit shares the iOS Safari rendering + JS engine, reproducing most "Safari is unhappy" bugs on Windows/Linux before a real phone.
- Make the projection **always-on** — a parametrised `browser_name`/device fixture so every test runs the mobile projection too. An opt-in projection gets forgotten.
- WebKit-on-Windows is *not* real iOS: no iOS shell, no real WKWebView memory limits, no Apple keyboard, no Add-to-Home-Screen container. For residual shell-only bugs, attach PC DevTools to a real phone via `ios-webkit-debug-proxy` (bridges the iOS Web Inspector to a local port Edge/Chrome DevTools can attach to). Playwright cannot drive real iOS Safari — only its bundled WebKit and the iOS Simulator on macOS.
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

After verification (unless told otherwise), restart and confirm liveness via a version/build endpoint showing the running process reflects new code — a health check is insufficient (stale process passes it). Report the build identifier; never hand off "done" over a stale process.

**Restart safely.** Kill only *this* app's process, identified precisely (port / PID / window title) — never a blanket process-name kill (`pythonw`, `node`, `python`), which also takes down siblings/shared services.

**A 'start' script is usually not a 'restart' script.** Re-running `launch_app.bat` / `tray.bat` / `npm start` over a live instance spawns a duplicate or silently no-ops if the port is bound. Pattern is **kill-then-start**. Document the recipe in this repo's `CLAUDE.md` under `## This repository`: which process to kill (port/PID lookup), which command relaunches it, what signal confirms the new build (e.g. `GET /api/version` returning current `git_sha`).

**A tray restart must reclaim service ports by PID (orphan-proof), not just `taskkill /T` the tray subtree.** Service children (webapp, session-host, tunnel) orphan when the tray dies/is replaced and keep their port; subtree-only kill misses them, so the fresh tray can't bind, fails silently, and the orphan serves stale code while the restart *reports success*.

- For each fixed loopback port the app **definitively owns**, `--restart` finds the listener, kills its owning PID, **then** starts. Scope the sweep to **this app's `.venv`** (siblings untouched); exclude **mutex-shared** ports (reclaiming kills the sibling's live process).
- Scope by the holder's **CommandLine**, *not* image path: on Python 3.14 Windows venvs, a venv-launched `pythonw.exe` re-execs the base interpreter, so image path shows the shared base while only CommandLine carries the `.venv` path — image-path guard never matches; reclaim silently no-ops.
- **Detect → kill → reclaim → start → verify lives in one committed helper, shelled via `-File` once** — never cmd `for /f` capture or inline `powershell -Command "…"` (`#54`): both return empty detection/reclaim data when `tray.bat` runs **non-interactively** (Git Bash → `cmd /c "tray.bat --restart"`, or a finisher skill's Bash tool) — nothing killed, `--restart` degrades to a plain start, which **adopts** whatever already serves the port (`WebappManager.start()` → `OWNERSHIP_EXTERNAL`) and reports healthy. Only the reclaim forces new code to load.
- **Verify by served `git_sha` vs repo `HEAD`, never a `healthz` 200** (stale adopted process passes health checks); mismatch must exit non-zero.
- Since `#153`, `tray_lifecycle.ps1` is **not** vendored per-app: every `tray.bat` calls the ONE shared, machine-local copy owned by `fleet-config` at `%USERPROFILE%/.claude/tray/tray_lifecycle.ps1` (exposed via `install.ps1` junction); hard-errors (never no-ops) if missing, naming fleet-config's `install.ps1` as the fix. A tray app still vendors `app/tray/single_instance.py` byte-for-byte (ships *with* the app).

Third tray-lifecycle gotcha, with **#12** (single-instance via named mutex, not bound TCP port) and **#13** (`CREATE_NO_WINDOW` when shelling to console tools); no conflict — #12 *detects* a running instance, this *cleans up* the previous one. Canonical `tray.bat` shape + reasoning: `docs/windows-tray.md`; copy-to-adapt `tray.bat.template` ships at scaffold root (replace four `__PLACEHOLDER__` tokens: app name, tray-launch args, tray-match regex, owned ports).

**Canonical restart invocation: `tray.bat --restart` — call it, don't hand-roll the kill.** One command = orphan-proof subtree-kill + per-`.venv` port reclaim + start, atomically. Automated finishers (`/issue-finish`, `/issue-yolo`) and any agent restart must run it, not re-derive a `Get-NetTCPConnection`/`taskkill` sequence (misses orphans). Manual port-PID kill is a *fallback* only for apps with no `--restart`. Each tray app's `## This repository` names `tray.bat --restart` plus the signal confirming the new build is live.

**A tray's single-instance guard must hold *in the tray process* (named mutex), and adopt-or-spawn must be *race-safe*.** Fourth tray-lifecycle gotcha, with **#12** / **#13** / **#29**. Launcher `.bat`'s pre-launch CIM detection is necessary but not sufficient: two near-simultaneous `tray.bat` runs both read the process table before either tray is visible. Per #12, the guarantee is a named mutex the tray holds for its lifetime: acquire at top of `run_tray()`; if already held, exit. Independently, `WebappManager.start()` doing `status()`-then-`Popen` is a check-then-act TOCTOU race: two trays both see "port free" and both spawn a duplicate uvicorn. Serialize check-then-spawn with a named mutex keyed on the owned port so the loser **adopts** the now-listening service instead of spawning. Both solved by one byte-identical primitive — `app/tray/single_instance.py` (`SingleInstance` + `cross_process_lock`) — **vendored verbatim** (only mutex *names* differ per app). Reasoning: `docs/windows-tray.md` (gotcha #4).

**The agent restarts a tray via `tray.bat --restart` fire-and-forget, then verifies with a *bounded* poll — never a foreground launch or unbounded wait.** A tray launcher holds the console it starts in, so a foreground tool call never returns and burns the 10-minute timeout. Call `--restart` non-blocking (background/detached) so the tool returns at once, then poll `GET /api/version` with a **hard timeout and attempt cap** (e.g. ≤30s), asserting `git_sha == HEAD` and reporting the build line; **fail loud** on a slow/failed boot.

A correct restart is **adopt / reclaim / spawn**: re-attach to healthy owned children, reclaim stale port-holders, spawn only what's missing. Classify children as **owned-and-cycled** (webapp/worker/cloudflared: live *inside* the tray subtree, die+respawn with new code, port in the reclaim list) vs **linked-but-independent** (session-host + its PTY shells/launched apps: must **survive**). Enforced structurally: linked children are **spawned re-parented out of the tray subtree** via `cmd /c start` — `taskkill /T` walks the parent-child PID tree, so `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP` do **not** escape it, only re-parenting does (verified empirically) — the fresh tray **re-adopts** them on start by port/identity. **Safety caveat:** until a tray with linked children is detach-compliant, `--restart` still kills those children — that tray's `CLAUDE.md` flags this and the agent confirms first. Mirrored in `/issue-finish` and the global restart skill (`#35`).

**Propagation freeze.** This repo vendors one channel verbatim into every sister repo that needs it: web-app UI components (`app/webapp/static/_vendored/`) and, for tray apps, `app/tray/single_instance.py` + `app/tray/watchdog.py`. (`tray_lifecycle.ps1` left this model in `#153` — machine-local infra, not app code; ownership: `docs/windows-tray.md`; channel rule "does it ship with the app?" in `app/webapp/static/_vendored/README.md`.)

- A vendored-component fix does **not** propagate until this scaffold's own verification gate is green — for the tray helper, includes behavioral e2e harness `tests/e2e/test_tray_lifecycle_behavior.py`, driving the real lifecycle end-to-end against the canonical file (resolved via `resolve_tray_lifecycle_path()`), not just structural/grep asserts.
- A **second** bug in the same vendored component **within the same day** freezes propagation entirely — harden and soak at source, no partial re-vendor, ship one cumulative wave once stable. (Tray cascade: `#144`–`#150`.)
- UI-component propagation is never a hand-filed per-repo issue; trigger criteria for the batched `/propagate-vendored` run live in `app/webapp/static/_vendored/README.md` ("Rules").
## Tray webapp self-heal (retry-with-backoff spawn + dead/wedged watchdog + breadcrumb log)
*Apply only if this project runs a Windows tray that owns a long-lived service (a uvicorn webapp, a worker, a tunnel).*

Covers the gap between deliberate restarts — without these three pieces the tray starts its webapp once and never looks at it again.

- **`/propagate-vendored` component: `app/tray/watchdog.py` (manifest key `tray_watchdog`).** Copy byte-for-byte like `app/tray/single_instance.py`; app-specific bits (probe, respawn action, breadcrumb path, toast) are call-site arguments. Carries three primitives: `retry_with_backoff`, `HealthWatchdog` (`rearm()`), `BreadcrumbLog`.
- **Initial spawn retries with backoff.** Unretried `manager.start()` at boot loses a transient race (port in `TIME_WAIT`, cert renewal in flight, dependency hub down) and leaves the webapp dead for the tray's lifetime. Wire `retry_with_backoff` into `_start()` on a background thread (icon still appears while uvicorn boots); final exhaustion must be **loud** — breadcrumb + toast, never swallowed.
- **Watchdog distinguishes dead from wedged; caller owns the decision.** `is_port_in_use() == False` → **dead**, auto-respawn (call `rearm()` if respawn fails, else it stays silent forever — watchdog is edge-triggered). Port bound but `/healthz` silent → **wedged**, **alert only** (`#386`; auto-kill can mask the real problem) — split lives in caller's `on_wedge`, not the vendored class. Probe must be a real `/healthz` round-trip; a port check cannot see a wedge.
- **Breadcrumb file is not optional** — `logging` can't replace it. `pythonw` has **no `sys.stderr`**, so `logging.basicConfig()`'s default handler discards the boot-time traceback; redirecting uvicorn's `stdout` to `DEVNULL` doesn't help since the missing record is the tray's own. Write a line at every start attempt, retry, wedge, respawn, recovery to `webapp/watchdog.log` (gitignored via `*.log`). Writes best-effort, never raise; rotates past ~1 MB.
- **Ref:** canonical wiring snippet, dead/wedged table and reasoning: `docs/windows-tray.md` gotcha #5. (`#201`; source instances `photo-ocr#110`, `app-launcher#386`.)

## Restart/deploy coverage — merged is not shipped
*Apply only if this project has more than one long-lived runtime component, or a runtime that lives outside the checkout, such that the project's restart or deploy recipe does not necessarily reach every live thing it owns.*

A merged PR, green gate, and successful restart prove only that *the one component the restart step touched* is live. Two failure shapes share one root cause: the finish flow reports "shipped" without observing the actual running target:

- **Out-of-tree runtime.** Code lives here; the thing it changes runs elsewhere (remote VM, device, tailnet peer) — merging changes nothing there until an explicit deploy step runs, even with a working deploy mechanism already in-repo (`home-automation#314`).
- **In-tree, restart-excluded runtime.** Process lives here and normally restarts with everything else, except one component is deliberately excluded (protecting live state) invisibly from the code. The "verified" restart then proves only the *other* component's build sha; half-restarted state can be worse than either whole version while the API still returns `{"ok": true}` (`app-launcher#611`/`#615`).

**The invariant:** a change must never be reportable as shipped while merely merged. Either the flow observed the actual target running the new code, or it says plainly it did not; where liveness can't be determined (target unreachable, sha unresolvable), report **unknown**, never assume fine.

**Declare every not-fully-covered runtime component** in this repo's own `CLAUDE.md`, in the same "This repository" section as the restart recipe — one entry per component the standard restart/deploy does not reach:

```markdown
## <component name>
- what/why: <what this component is; why it's excluded from the standard restart, or where it lives if out-of-tree>
- update command: `<the one supported command>` (confirmation-gated if destructive)
- liveness signal: `<field or probe>` — e.g. `GET /api/version`'s `<component>.stale`
- NOT restarted/deployed by: `<the standard restart/finish flow>`
```

**Extend the build-identity endpoint per component, not just per process.** Where `/api/version` exists (per "Webapp PWA required surfaces"), report a sub-block per not-fully-covered component: `{reachable, git_sha, captured_at, stale}`. `stale` compares that component's captured identity (captured once, at process start/import, via a shared `build_info.py`-style helper — not read live) against the repo's current HEAD sha; must be `None`/unknown, not `false`, when either side is unresolvable. For an out-of-tree target with no HTTP endpoint, probe the target itself (e.g. hit its live API to confirm a pushed config took effect) — same "observe the target, not the repo" principle, different transport.

**Retry inside the capture, never after it.** Capture-once must survive a *transient* failure at capture time: a bounded retry (few attempts, short backoff) inside the capture call, without breaking the "captured once, at process start" semantic. Re-resolving later (e.g. per `/api/version` request) is the tempting wrong fix: `git_sha` would track live git state instead of what the process loaded, so a stale process could report a fresh `HEAD` as confident **"fresh"** — worse than `unknown`, violating the never-a-confident-false rule above. Once retries exhaust, identity stays `unknown` for that process's lifetime, permanently and honestly — never silently retried outside the capture path. (Observed: `app-launcher`'s session-host reported `unknown` for 8 days off one transient `git` failure at import — `app-launcher#825`.)

**A detached/console-less child needs a real log destination, or its failure explanation is discarded.** The gap the tray watchdog breadcrumb (`#201`) closes applies to any detached service child (session-host, worker): `pythonw` has no `sys.stderr`, so the default `logging.basicConfig()` handler writes to a stderr nobody reads, and piping `stdout`/`stderr` to `DEVNULL` discards the diagnostics that would explain a frozen capture or dead process. Give every detached child a real file target (append mode); fall back to `DEVNULL` only when the log path is unwritable, never as default.

**Surface the gap at verify time, not just finish time.** Where a diff-classification mechanism exists (e.g. `classify_e2e.py`'s path-to-tier routing), reuse its output to print an advisory warning in `verify-before-ship` when the diff touches a declared component's paths, naming the field to check before reporting shipped. Advisory only — must not fail the gate, which can't observe a remote/excluded target.

**Finish flow's obligation:** when a project declares not-covered components and the diff touched their paths, `/issue-finish`-shaped flows check that component's liveness signal after restarting and, if stale/unknown, state so explicitly — "merged but not yet live: `<component>` requires `<the declared manual action>`" — rather than reporting shipped. Where the manual action needs a human (credentials, physical device, explicit destructive confirmation), the flow stops and names precisely what's needed rather than closing the issue as done.

**Ref:** convention + per-project declaration shape live here; skill-side enforcement (reading the declaration, checking the liveness field, wording the finish summary) lives in `fleet-config`'s `skills/issue-finish/SKILL.md`. Reference implementation: `app-launcher`'s `src/build_info.py` (shared git-sha + capture-timestamp helper, `build_identity(attempts=3, backoff_seconds=0.3)` retrying inside the capture) + `/api/version`'s `session_host` sub-block + `scripts/restart-session-host.ps1` (`-Confirm`-gated, manual-only, never wired into a normal ship flow) + `verify-before-ship.ps1`'s advisory warning reusing `classify_e2e.py`'s routing output (`app-launcher#615`). `build_info` is catalogued as a `[components]` entry (manifest key `build_info`, `src/build_info.py`) — small, stdlib-only, non-obvious retry/logging semantics worth keeping in one place; `/propagate-vendored build_info` is the fan-out path for adopters (`#247`). (`#199`; retry + detached-logging corollary `#246`; source instances `home-automation#314`, `app-launcher#611`/`#615`/`#825`/`#826`.)
## Multi-repo agent fanout — a dispatched agent works in a worktree, never the primary checkout
*Apply only if this project ships tooling that fans work out across several repos — a scatter-gather skill, a batch runner, a board/scheduler that spawns per-repo agent sessions.*

Global `CLAUDE.md`'s concurrent same-repo rule (first come owns `main`, worktree after) is claim-based; a running process (live webapp/tray, junctioned config dir) publishes no claim, so a dispatched agent can legitimately win the primary and edit files out from under it.

- **Worktree-only, unconditionally and uniformly.** Every dispatched per-repo agent builds in an isolated sibling worktree (`<repo>-wt-<N>`, primary's `.venv` junctioned in) for every repo — never "primary unless claimed," never a per-repo allow-list of which repos happen to run something live (wrong the day a repo grows a tray). Interactive human sessions keep claim-or-worktree (one worktree per issue is overhead for a single attended session).
- **Enforce in the tool, not agent prose (load-bearing).** Advisory rules lose. The claim helper itself forces worktree mode when the explicit flag is passed OR the dispatch marker is present in the environment — no primary claim attempted or published either way. One documented env escape hatch for a dispatched flow that must hold the primary; explicit flag still wins over it. Prose explains; code enforces.
- **Teardown is a terminal step of every lane; residue halts the run.** Each lane: record outcome (+ any WIP sha) on the issue, remove worktree, release claim, delete branch, confirm primary back on a clean default branch. Serialize lanes (at most one worktree fleet-wide at any instant); stop the run on a lane that can't return to clean. Post-flight verification enumerates worktrees, sibling `-wt-*` dirs, stray branches and dirty trees across every touched repo — checking only merged repos' primaries let a run report "0 failed" over 11 strays.
- **Teardown must not assume the happy path.** Strip the `.venv` junction before removing the tree on every path including fallback (a reparse point walked by recursive delete is the classic footgun). Don't derive the primary via `rev-parse` from inside the worktree — git deregisters it while the directory survives, so the call exits non-zero. Exit non-zero naming the surviving path rather than reporting a false clean.
- **A live-e2e guard refusal is a hard stop for a dispatched agent.** The opt-in env var represents an attended human decision about a live app; an unattended fanout agent hitting the refusal reports and stops — never sets the flag to get past it.
- **Pin the mandate with an executable guard.** Load-bearing prose spread across dispatch paths can be silently dropped by a purge/rewrite. An acceptance test asserting the mandate's presence in each dispatch path and in the claim helper's implementation keeps it from evaporating.

**Ref:** convention here; implementation (claim/worktree helper + dispatch paths) in `fleet-config` (`skills/_lib/worktree_claim.py`'s `acquire --force-worktree`, `APP_LAUNCHER_SESSION_ID` trigger, `WORKTREE_CLAIM_ALLOW_PRIMARY` escape hatch). (`#202`; source instances `fleet-config#515`/`#518`/`#522`/`#525`/`#526`/`#527`/`#528`.)

---

## This repository
<!-- Replaced per repo. Keep to two sentences max. -->
<one sentence: what this project is>.
See `README.md` for setup, layout, and usage.
