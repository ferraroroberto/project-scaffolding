# Project Instructions

Canonical instructions for AI coding agents working in this repository. Claude Code reads this file directly as project memory. Other agents (Cursor, Codex, etc.) reach it via the one-line `AGENTS.md` pointer.

> **Scope — project-shaped guidance only.** This master owns only what is *specific to a project's shape* — Streamlit, GitHub-Actions CI, end-to-end UI testing, a tray / long-lived process — each section gated *"apply only if…"* and inherited by a project of that shape. **Universal** dev-workflow directives (plan mode, asking, before/while editing, execution, conventions, git, branch & PR pipeline, planning, documentation discipline, senior-dev check) live once in the machine config (`fleet-config/global-CLAUDE.md`, installed as `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`) and are **not** restated here. The test for any rule: *"would it apply to a bare repo with no app?"* Yes → global; no → here. Nothing belongs in both — the `/context-audit` skill enforces this single-home split weekly. (Standard: `ferraroroberto/project-scaffolding#68`.)

## Agent config artifacts (`AGENTS.md` pointer; `.agents/` / `.codex/` gitignored)
*Applies to every repo — app or not.*

Codex is an intentionally-supported second agent on this machine, so the fleet keeps **one** standard for cross-agent config artifacts — not the auto-generated noise a Codex/AGENTS.md generator once dropped fleet-wide (verbatim `Claude`→`Codex` find-replace of each `CLAUDE.md`, mirror `.agents/skills/` + `.codex/hooks.json`, broken `~/.Codex/...` paths).

- **`AGENTS.md` is a committed one-line pointer to `CLAUDE.md` — never a find-replaced copy.** The machine-scope instructions are the single global file symlinked into each agent home (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, …) by `fleet-config/install.ps1`; the per-repo `AGENTS.md` just points non-Claude tools at this repo's `CLAUDE.md`. Being static, it is drift-free by construction — no generator, no sync step, nothing to regenerate when `CLAUDE.md` changes.
- **`.agents/` and `.codex/` are gitignored, never committed.** They are per-repo auto-generated mirror/tooling noise; the real, maintained Codex config lives machine-scope in `~/.codex/`. This scaffold's `.gitignore` excludes them (consistent with `fleet-config`, which already ignores `.codex/`), while deliberately **not** ignoring the committed `AGENTS.md`.
- **Don't diverge.** A cloned repo inherits both the committed `AGENTS.md` pointer and the two `.gitignore` lines by default. The decision *record* lives here (not in global `CLAUDE.md`) because it produces per-repo **files** the scaffold templates — global `CLAUDE.md` is a single machine file never copied into repos. Rolling the `.gitignore` delta + `AGENTS.md` pointer out to sister repos is a follow-up fleet sweep. (Decision record: `ferraroroberto/project-scaffolding#28`.)

## Streamlit conventions
*Apply only if this project uses Streamlit.*

- `st.set_page_config(layout="wide", page_title="...")` MUST be the first Streamlit call.
- Use `width="stretch"` (and `width="content"` where appropriate) in new and modified code. **Never** introduce new `use_container_width=True` — it is deprecated. When you touch existing code that uses `use_container_width`, migrate it.
- All mutable state in `st.session_state`. No module-level globals.
- `@st.cache_data` for DataFrames/files; `@st.cache_resource` for DB clients/models.
- Every widget needs a stable, explicit `key=`.
- UI code only in the UI directory (e.g. `app/`). Data logic stays in the non-UI package (e.g. `src/`). Never import `streamlit` from non-UI code.
- User feedback via `st.error()` / `st.warning()` / `st.success()`, not `st.write()`.
- **App layout:** the main file (e.g. `app.py`) handles only page config, shared state, the sidebar, and routing. Default to native multipage navigation — `st.navigation` + `st.Page`, one view per file exposing a `render()` function (the pattern this scaffold ships). Use `st.tabs()` for sub-sections *within* a view, and a sidebar radio only when asked.
- **Ask before assuming (Streamlit specifics):** `st.session_state` key names & scope; caching strategy (`@st.cache_data` TTL vs. `@st.cache_resource`); widget `key=` names & input sources; page placement (new page vs. a section in an existing page). (The universal "ask before assuming" directive is in global.)

## Web-app visual identity (fleet design system)
*Apply only if this project serves a FastAPI + static PWA web app. Streamlit POC spikes are exempt.*

A fleet web app inherits its look **and** its navigation from one place — it re-authors neither. The split follows single-home-by-altitude: **`fleet-config`** owns the *spec* (`design.md` + `design.dark.md`, junctioned into `~/.claude`, plus the `/design-sync` skill); **this scaffold** owns the *vendored implementation* (`app/webapp/static/_vendored/`).

- **Tokens come from the spec, not from you.** Wire your CSS custom properties to `~/.claude/design.md` (light) + `~/.claude/design.dark.md` (dark) — colors, typography, spacing, radii. Define the tokens in your app's `:root` / `[data-theme]` blocks pointing at those values; **don't** copy the spec into your repo and **don't** invent a second accent or per-app palette. `/design-sync` reports drift.
- **Nav is vendored, not re-implemented.** The primary navigation — the floating bottom-tab pill (desktop segmented control → mobile pill, the fleet *navigation contract*) — is vendored from `app/webapp/static/_vendored/nav/` (`nav-tabs.js` + `nav-tabs.css` + `nav-tabs.html`). Copy the folder **verbatim**, adapt only your markup (which tabs) and the `storageKey`. The nav markup is deliberately a direct `<body>` child and sibling of `<main class="app">`, never nested inside the content wrapper/scroller: `home-automation#232` proved on a real iPhone PWA that iOS can capture fixed-position descendants of scrollers and anchor them to short-tab content instead of the viewport. This is the same "copy byte-for-byte, never fork per-app" rule as the tray's `single_instance.py` (`tray_lifecycle.ps1` moved to a shared machine-local copy in `project-scaffolding#153` — see the "Restart and verify before hand-off" section below).
- **`_vendored/` is the UI component channel.** New shared HTML/CSS/JS components live under `app/webapp/static/_vendored/<component>/`, normalized from the best existing fleet implementation. Don't hand-copy a sibling app's snippet into a new app — vendor it from here so there's one source of truth. See `app/webapp/static/_vendored/README.md` for the convention and how to add a component.
- **Don't diverge / don't re-author.** A change to a vendored component or the token contract is made *here* and re-vendored downstream, never forked in a consuming app. (Standard: `ferraroroberto/project-scaffolding#79`; aligns to `ferraroroberto/fleet-config#178`.)

## UX surface — diff-keyed design-conformance gate
*Apply only if this project serves a FastAPI + static PWA web app. Streamlit POC spikes are exempt.*

When an issue touches a web app's UX, the finish flow runs a **gate** checking the change still conforms to the spec — and crucially, *that the rendered view isn't visually broken*. This is the enforcement arm of the section above: the don't-introduce-new-drift counterpart to the periodic fleet-wide audit (`ferraroroberto/fleet-config#180`), not a duplicate of it.

**Two distinct checks — keep them separate.** A *token check* (`/design-sync`-style) diffs the CSS custom properties (light + dark) and the nav contract against the spec: static, no browser, **never renders the page**, so it catches "accent drifted from spec" but is blind to "nav pushed off-screen / cards overlap." A *visual verification* (`verify`-style) launches the live app, drives the touched view in a headed browser, and screenshots it — the only check that actually *sees* the result, and the token-expensive leg. Not substitutes: cheap-and-blind vs sees-but-costs. A real gate uses both, scoped to the diff.

**Each project declares a `## UX surface` block in its own `CLAUDE.md`** — the per-project *instance* the skills read, exactly as `## CI expectations` does for the e2e-surface skip. Don't inline these paths into the skill; they differ per repo. **This scaffold ships the block below as a _live_ declaration, not a fenced sample** — so a cloned repo inherits a parseable block, and turning the gate on is a one-word edit: flip `design spec applies` to `yes` and adapt the paths/views once the repo serves a FastAPI + static PWA. A repo with no web UI leaves it `no` and the gate stays a permanent no-op. Keep the block under this section's heading — `ux_surface.py` tolerates the descriptive `— …` suffix, so do **not** add a second `## UX surface` heading (the parser would match this one first and read nothing).

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
- **Deterministic, diff-keyed — not a per-run LLM judgment.** The trigger is purely: does `git diff <main>...HEAD` intersect the declared `paths`? Yes → the gate runs. No → skip silently and **state it** in the finish summary (`no UX surface touched`). Zero added cost on the ~90% of issues that touch no UX. This is the same path-keyed mechanism as the `## CI expectations` e2e-surface skip — the "judgment" is just a glob intersection, which is why it stays consistent run to run.
- **Cheap design-aware load at `/issue-start`.** When the picked issue is *likely* to touch the UX surface, read `~/.claude/design.md` + `design.dark.md` into context **before** building — two file reads, no browser, ~free. The build starts design-aware, which is what prevents end-of-flow rework. No `/design-sync` and no screenshot at start.
- **Gate at `/issue-finish` (and `/issue-yolo`), only when the diff touched the surface** — two legs:
  - **Token check, fix-now semantics.** Compare the touched UX files (CSS custom properties light + dark + the nav contract) to the spec and **fix material drift in this branch before merge.** Note the semantics differ from vanilla `/design-sync`, whose default *files-and-defers* a `design-drift` issue: the finish gate's job is to **not introduce** drift, not to log it for later. (Vanilla `/design-sync` stays as-is for the periodic sweep — different job.)
  - **One screenshot of the touched view.** The finish flow already restarts the tray and version-verifies, so the app is live at that point — screenshot the affected view once (eyeball nav pill, layout, palette against the spec) via the `verify` skill and attach it to the PR body. Diff-scoped, never a whole-app sweep by default.
- **Manual overrides** (mirroring `/issue-start`'s `now`/`plan`): `ux` / `design` forces the gate even if the diff looks code-only; `no-ux` skips it when the detector over-fires; `ux-full` audits the whole app's `key views`, not just the diff — the one expensive path, opt-in only.
- **Materiality bar** (carried over from `/design-sync`): a 1-unit radius/spacing nitpick is not a blocker; a wrong canvas color, a missing dark theme, a hand-rolled nav, or a visibly broken layout is.
- **Keep-the-human-in-control.** The agent always **states** the gate decision (ran / skipped / `ux-full`, plus any drift it fixed) in the finish summary, so the user can veto.

**Where each piece lives:** this scaffold documents the convention + the block default; the **skill mechanism** in `fleet-config` `skills/issue-{start,finish,yolo}/SKILL.md` (synced to `~/.claude`, tracked in `ferraroroberto/fleet-config#195`); the **per-project instances** in each project's own `## UX surface` block; the periodic fleet-wide drift sweep is a separate job (`ferraroroberto/fleet-config#180`). Browser screenshots must go through the `verify` skill's stealth-Chrome launch (real Chrome, no automation infobar, per the global `CLAUDE.md`) — never re-inline launch args. (Decision record: `ferraroroberto/project-scaffolding#83`.)

## HTTPS provisioning
*Apply only if this project serves a FastAPI + static PWA web app. Streamlit POC spikes are exempt.*

An installed PWA needs HTTPS (Service Workers + Web Push are HTTPS-only). How you provision the cert is decided by **how the app is reached remotely** — and the preferred path eliminates the per-device trust chore the fleet has otherwise re-paid on every app.

- **Reached over Tailscale → `tailscale cert` (preferred).** Provision a **real Let's Encrypt leaf** for the tailnet MagicDNS name with `scripts/gen_tailscale_cert.py`. Tailscale owns the `ts.net` domain and answers the ACME DNS-01 challenge, so there is **no public DNS name, no HTTP-01/DNS-01 setup, and no inbound exposure** to arrange — and because every tailnet device already trusts Let's Encrypt, there are **zero per-device trust steps**: no CA install, no `.mobileconfig`, no iOS Certificate-Trust toggle, no Chrome-restart gotcha. This is *simpler* than the self-signed dance, not overkill. One-time prereq: enable HTTPS in the tailnet admin console (**DNS → HTTPS Certificates**), once per tailnet.
- **Auto-renew on startup is mandatory.** The LE leaf is **~90 days** (vs a self-signed root's 10 years), so a manual re-issue *will* be forgotten. `gen_tailscale_cert.py --check` renews **only** a `.ts.net` cert expiring within ~30 days, **no-ops a self-signed cert**, and never blocks startup on error. Wire `--check` into the **app's own webapp launcher** (e.g. `webapp.bat`), before uvicorn binds — **not** the generic `tray.bat.template` (vendored tray lifecycle; cert provisioning is app-specific). Reference wire-up: `grocery-shopping-automation`'s `webapp.bat`.
- **LAN-only / no Tailscale → self-signed CA (fallback).** A genuinely loopback/LAN-only app keeps the self-signed CA + leaf (`gen_ssl_cert.py`) and the per-device trust dance (`certutil -user -addstore Root ca.pem` + the full-Chrome-restart gotcha; iOS `/install-ca` `.mobileconfig` + Certificate-Trust toggle). This remains correct **only** when there is no tailnet. The in-app `/install-ca` Settings affordance (`#74`) is scoped to this fallback path — a `tailscale cert` app does not ship it.
- **Don't diverge.** The convention lives here; the full didactic procedure (commands, the admin-console step, the iPhone install) is `docs/app-onboarding.md` §2–§3. A cloned PWA inherits this decision by default. (Decision record: `ferraroroberto/project-scaffolding#89`.)

## Webapp PWA required surfaces (build-identity footer + Settings/CA-install)
*Apply only if this project serves a FastAPI + static PWA web app. Streamlit POC spikes are exempt.*

Every fleet PWA ships two small surfaces that have otherwise been re-derived (or forgotten) per app. They belong to the canonical webapp shape so a cloned app inherits them, not copies them by hand from a sibling.

- **Build-identity footer — `GET /api/version` → `{git_sha, built_at}`.** Capture the values **once at module load** via a hardened `git rev-parse --short HEAD` (`git -C <project-root>`, `stdin=subprocess.DEVNULL` + `creationflags=CREATE_NO_WINDOW` so the windowless tray never flashes a console), and render a `Build: <sha> · <ts>` line as a plain `<p>` **outside every card**. This is the difference between "the tray restarted" and "the *new build* is live": a `/healthz` 200 passes on a stale process, a matching `git_sha` does not — the `/issue-finish` + `/issue-yolo` tray-restart verification **depends on this endpoint existing**. The endpoint is **auth-gated** (loopback bypasses; the PWA attaches the bearer via the page's `jsonApi`) so a build SHA is never exposed to an unauthenticated remote caller. This footer is **universal** — present regardless of how HTTPS is provisioned.
- **Settings block — a collapsible `⚙️ Settings` `<details>` with an Install-certificate link.** The generic, every-PWA portion is an **Install certificate** link to `/install-ca` (the route that serves the iOS `.mobileconfig`). `/install-ca` is **auth-exempt**, so the link is a plain `<a href>` navigation that works over Tailscale without a token — **not** a `jsonApi` fetch. Include a short iOS trust how-to beside it. The block's **app-specific** contents (config fields, passkey/WebAuthn, tunnel status) are *not* part of the standard — only the collapsible block + the CA-install affordance are.
- **The CA-install link is conditional on the HTTPS path (ties to `#89`).** It exists only to make the self-signed-CA *trust dance* bearable, so it ships **only on the self-signed / LAN-only fallback path**. A `tailscale cert` app (the preferred path — real LE leaf, zero per-device trust) **omits or hides** the `/install-ca` Settings link, since there is nothing to install. The `/api/version` footer stays regardless.
- **Don't diverge.** The convention lives here. The scaffold ships no starter FastAPI server today, so this is documented (not seeded) — a vendored `_vendored/settings/` component is a separate future step (see `app/webapp/static/_vendored/README.md`). Reference implementations: `app-launcher` `app/webapp/routers/misc.py` + its `static/{index.html,main.js}`, and `home-automation`. (Decision record: `ferraroroberto/project-scaffolding#74`.)

## Webapp PWA static-asset cache-busting (`CachingStaticFiles` + fleet hash)
*Apply only if this project serves a FastAPI + static PWA web app. Streamlit POC spikes are exempt.*

iOS Safari — installed home-screen PWAs especially — heuristic-caches static assets served by a bare Starlette `StaticFiles` mount (it sends only `ETag`/`Last-Modified`, **no explicit `Cache-Control`**). After a deploy + tray restart the device keeps running the **old cached JS/CSS** while `/api/version` reports the new build — the footer reads "fresh" while the code is stale, and only deleting + re-adding the PWA clears it. Every fleet PWA (`app-launcher`, `photo-ocr`, `voice-transcriber`, `home-automation`, `grocery-shopping-automation`, `whatsapp-radar`) ships the same fix: a **required convention**, not an optional extra.

- **One canonical reference, copied — not re-derived.** `home-automation/src/static_versioning.py` is the nominated canonical implementation (the most mature of the five independent copies). A new PWA app copies that module + the `CachingStaticFiles(StaticFiles)` subclass (`home-automation/app/webapp/server.py`), adapting nothing but the static dir. The canonical method names are **`BuildInfo.stamp_html` / `stamp_js`** (wrapping `rewrite_index_html` / `rewrite_js_imports`) — this resolves the old photo-ocr `stamp_js` vs voice-transcriber `rewrite_js_imports` split into one API.
- **Fleet hash, not a naive per-file hash.** The webapp is an ES-module graph (`index.html` → `main.js` → imported modules). A per-file hash goes stale on transitive edits: if `state.js` changes but `main.js`'s bytes don't, `main.js`'s own hash is unchanged yet the graph it pulls in is different. So a single **fleet hash** = one SHA-256 over the concatenation of every hashable file's per-file hash; any edit to any module rotates *every* `?v=` stamp and the whole (tiny) graph is re-fetched.
- **Stamp idempotently, degrade gracefully.** The import/href regexes also capture an existing `?v=…` and replace it, so re-stamping an already-served body is safe; an unreadable static dir or missing file falls back to **unstamped** URLs rather than crashing the page.
- **Per-suffix `Cache-Control`; the shell always revalidates.** `.js`/`.css` get `public, max-age=31536000, immutable` (safe because the fleet hash is the cache key); manifest/icons get a daily `public, max-age=86400`. The **shell** (`index.html` root route) is served `Cache-Control: no-cache, must-revalidate` so the entry point always revalidates — otherwise a cached shell still points at the old entry module and the hashing buys nothing.
- **Don't diverge.** The convention lives here; the trimmed `CachingStaticFiles` + fleet-hash reference snippet is in `docs/app-onboarding.md` §4. Service workers / offline caching are deliberately **not** used in the fleet. (Decision record: `ferraroroberto/project-scaffolding#78`.)

## Windows event-loop pinning (uvicorn)
*Apply only if this project serves a FastAPI + static PWA web app. Streamlit POC spikes are exempt.*

- Every uvicorn spawn point (tray subprocess spawn via `manager.py`, a programmatic `uvicorn.run()`, `.bat` launcher scripts, e2e autoboot spawns) must pass a pinned selector-loop factory (`--loop`/`loop=`) — asyncio's default Windows proactor loop wedges the listening socket on any aborted client connection (`app-launcher#388`). Worked shim + rationale: `docs/app-onboarding.md` §1; reference implementation: `app-launcher`'s `app/webapp/event_loop.py` (`selector_loop_factory`).

## Windows console-subprocess suppression (`CREATE_NO_WINDOW`)
*Apply only if this project runs a long-lived Windows process (tray, daemon, GUI) without its own console — e.g. launched via `pythonw` — that shells out to a console-based CLI tool (`docker`, `nvidia-smi`, `git`, `taskkill`, …).*

- Every console-tool subprocess call (`subprocess.run`/`subprocess.Popen`, `asyncio.create_subprocess_exec`) must pass `creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0` — a console-less parent (no window of its own) makes Windows allocate a fresh console for each child, flashing a visible window; repeated on a poll loop this reads as malware or a stuck app (`local-llm-hub`'s Hub-tab health poll, `project-scaffolding#13`). Centralize behind one small helper (e.g. `_no_window_flag()`) imported everywhere rather than re-inlining the literal at each call site — `asyncio.create_subprocess_exec` accepts the same flag and is easy to miss vs. the sync API.
- A detached long-running child additionally wants `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` as appropriate.
- Related trap: a `pythonw` child launched without a redirected `stdout`/`stderr` crashes on its first log write (no console to write to) — always give it a real target (pipe or file).
- Worked helper: `docs/app-onboarding.md` §1.

## FastAPI + SQLite connection lifecycle (one `get_db` `Depends` dependency)
*Apply only if this project is a FastAPI app backed by SQLite.*

FastAPI's documented pattern for a per-request database connection is a single dependency that opens the connection, `yield`s it, and closes it in a `finally`, injected via `Depends` — one place owns open/close, and the connection is guaranteed closed even when the handler raises. Fleet apps grew the lifecycle by hand instead: `whatsapp-radar#100` (the motivating instance) had connect → use → close copy-pasted across **11 handlers**, each able to leak a handle on an early return or exception, all needing edits together to change connection setup.

- **One dependency owns the connection.** Expose the connection through one `get_db()` that connects, sets `row_factory = sqlite3.Row` + `PRAGMA journal_mode=WAL`, then `try: yield / finally: conn.close()`. Handlers take `db: sqlite3.Connection = Depends(get_db)` rather than opening their own. Centralizing setup (pragmas, row factory, timeout) in that one place stops it drifting between handlers. Acceptance: a derived app has **zero** per-handler `sqlite3.connect(...)` calls in its routers.
- **SQLite + stdlib `sqlite3` stays the fleet default.** This convention is only about the *lifecycle dependency* — no ORM, no async driver, no connection pooling. (Apps that legitimately need a long-lived single connection — none currently identified — are the documented exception.)
- **Don't diverge.** The convention lives here; the canonical `get_db` + `Depends` reference snippet is in `docs/app-onboarding.md` §4. This is the documented FastAPI idiom — "write down what we should already be doing," not a novel design. (Decision record: `ferraroroberto/project-scaffolding#96`; source instance `ferraroroberto/whatsapp-radar#100`.)

## Outbound-connection discipline (pooled sessions, backoff, bounded fan-out, no leaked children)
*Apply only if this project runs a long-lived process (tray, daemon, webapp, poll loop) that makes outbound HTTP/TCP calls — to another local app, an external API, or hardware.*

On Windows, each closed outbound TCP connection parks its ephemeral port in `TIME_WAIT` for ~120s against a 16,384-entry dynamic range; a few busy pollers issuing a fresh connection per call are enough to exhaust the range and stall every process on the machine from opening any outbound socket for minutes (root cause: `fleet-config#440`). This reads as a mysterious whole-machine outage rather than an obvious bug in the offending process, so it's a stated convention rather than something re-discovered per repo.

- **Reuse connections — is a `/propagate-vendored` component: `src/pooled_http.py` (manifest key `pooled_http`).** A bare `requests.get`/`requests.post` inside a poll loop, health check, or per-item fan-out is a defect, not a style preference: it opens a fresh connection — and a fresh `TIME_WAIT` port — on every call. `build_session(pool_size)` returns a `requests.Session` with a sized, keep-alive `HTTPAdapter` mounted on both schemes, built once (e.g. at module import) and never reconfigured per call; `pooled_request(method, url, *, timeout, session=SESSION, **kwargs)` dispatches through it and retries once on `requests.exceptions.ConnectionError` (safe even for non-idempotent methods — the failed attempt never reached the server — so a sibling process's restart surfaces as a clean reconnect, not a spurious error on the next poll). This is vendorable because the *mechanism* — build a pooled session once, wrap dispatch with a single retry — is shape-independent; only the pool size and the target URL are call-site arguments, exactly the `single_instance.py` / `tests/e2e/_e2e_live_guard.py` pattern (mutex names / port+flag are arguments; the primitive itself is byte-identical). Reference implementation, with measured before/after evidence: `app-launcher#605`'s `src/_loopback_http.py` (145 → 0 `TIME_WAIT` sockets to its session-host after adoption). `requests` is a real added dependency for a project that vendors this file — it is *not* pulled into every scaffolded project's `requirements.txt` by default; only this repo's own copy (used to prove the module via its unit tests) declares it.
- **Back off what is failing — prose only, no vendored helper (yet).** A polling client that keeps hammering an endpoint returning errors or timeouts at full rate burns a finite kernel resource for no new information. Failures should escalate the retry interval and recover it on success, so a permanently-dead endpoint settles at a slow retry rather than the hot-path cadence. Unlike the pooling case above, this stays prose because there is no proven reference implementation yet to vendor from — the motivating instance (`home-automation#537`, Tuya reconnecting 3x/second against permanently-unreachable devices) is still open. Extracting a shared backoff tracker is a natural follow-up once a real fix lands and proves the shape (same bar as the pooled-session component: propagate a proven fix, not a theoretical one).
- **Cap the fan-out — prose only.** Polling N devices/endpoints concurrently should bound concurrency (an `asyncio.Semaphore(N)` or equivalent around the poll loop) rather than firing all N at once every tick. This is a 2-3 line idiom that differs by concurrency model (`asyncio` vs `threading` vs a plain counter) — too thin and too framework-specific to be worth a vendored wrapper; write it inline at the poll loop.
- **Do not leak child processes — prose only; no active sweep shipped here.** Playwright teardown in particular: an e2e suite must close every browser/context it opens, including on a failed or interrupted run (a `finally`/fixture-teardown path, not just the happy path) — a leaked `WebKitNetworkProcess`/browser process holds sockets and handles indefinitely. A stale-orphan *detection* (dead-parent browser processes older than some threshold) belongs in the pre-ship gate as a reported signal, not a human's head to remember — but this convention does not ship an active killer script: on a shared dev machine, blindly killing browser processes by name risks taking down another session's in-flight e2e run, so any sweep must be scoped to genuinely-orphaned processes (dead parent PID) and is a deliberate follow-up, not bundled into this PR.

## GitHub Actions CI conventions
*Apply whenever this project adds a `.github/workflows/` file.*

- **Pin a dated Windows runner.** Use `runs-on: windows-2025`, never `windows-latest`. GitHub is redirecting `windows-latest` to `windows-2025` (deadline June 2026); for a Windows-only tray/daemon app that spawns real processes (PTYs, uvicorn, Chromium), the OS image silently changing under you is exactly the environment shift that turns a green gate red without a code change. Pin the label so the runner is an explicit, reviewable choice.
- **Use Node-24 action majors.** `actions/checkout@v4`, `actions/setup-python@v5`, and `actions/upload-artifact@v4` all run on Node 20, which is deprecated (forced Node 24 starting June 16 2026; Node 20 removed September 16 2026). Use the current majors that run on Node 24: `checkout@v6`, `setup-python@v6`, `upload-artifact@v7`. Inputs are unchanged for standard usage, so the bump is drop-in.
- **Trigger once per commit: `push:[main]` + `pull_request:[main]`.** Gate `main` with two events that each own exactly one job — `push` to `main` (the post-merge integration gate) and `pull_request` to `main` (validates every feature branch). Do **not** trigger `push` on feature branches (`push:` with no `branches:` filter, or `push: branches-ignore: [main]`): while a PR is open, every branch push fires *both* `push` and `pull_request`, running the same gate **twice on the same commit** — double runtime, double flake exposure, zero added coverage. The `branches-ignore: [main]` shape also silently *omits* the post-merge `main` gate, so the merge commit (which can differ from what the PR validated, if `main` moved underneath it) is never CI-gated. `concurrency` cannot fix this: `github.ref` differs between the two events (`refs/heads/<branch>` for push vs `refs/pull/<N>/merge` for pull_request), so they land in separate concurrency groups and both survive — `concurrency` only collapses successive pushes to the *same* ref. The only thing given up — CI on a branch you pushed but never opened a PR for — is a non-loss: the standard `/issue-finish` flow always pushes and immediately opens the PR.

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

Run-count, wrong shape vs this convention:

| Moment | `push: branches-ignore: [main]` + `pull_request` | This convention |
|---|---|---|
| Push to a feature branch with an open PR | **2 runs** (push + pull_request) | **1 run** (pull_request `synchronize`) |
| Push to a feature branch, no PR yet | 1 run | 0 (open the PR before you need CI) |
| Merge commit on `main` | **0 runs** (main is ignored) | 1 run (post-merge gate) |

**Sister-repo tracking:** when a fleet repo still has the old runner/actions (`#25`) or the duplicate `push`-on-branches trigger (`#38`), it carries a pointer issue back to the canonical decision record in `ferraroroberto/project-scaffolding`. Fix it before the deprecation deadline rather than after.

## CI is advisory — `## CI expectations` block + e2e-surface skip rule
*Apply whenever this project has a `.github/workflows/` file **and** a local verification gate.*

**CI is advisory, not a required gate.** The fleet's e2e workflows run on repos with **no branch protection**, so their checks are not required to merge. The **local gate** (`scripts/verify-before-ship.ps1`, or `pytest + ruff + mypy`) is the contract; CI is supplementary. The agent must not treat `gh pr checks --watch` as a mandatory blocking wall.

**CI's only signal beyond the local gate is the e2e suite.** The local gate runs `pytest + ruff + mypy` but **skips the Playwright e2e leg** (it needs browsers + a live webapp). So the *only* thing CI runs that the local gate didn't is the e2e suite — which is also the known-flaky part (browser/PTY input wedging on the slower hosted Windows runner). **Consequence:** a diff that touches **none** of the project's e2e surface gains nothing from waiting on CI, yet a wedged WebKit browser can still block the merge up to the `timeout-minutes` cap. Waiting there is pure cost, no signal.

**Each project declares a `## CI expectations` block in its own `CLAUDE.md`** (the per-project *instance* — durations, flaky leg, e2e-surface paths). `/issue-finish` reads it. Don't inline these values into the skill; they differ per repo. Block template (fill the bracketed values):

```markdown
## CI expectations
- Workflow `[.github/workflows/e2e.yml]`, job `[verify-before-ship]`, on every PR. **Advisory, not required** (no branch protection) — the local gate is the contract.
- Typical green: **~[N] min**. Investigate at **>[2N] min**; treat as wedged at **>[~4N] min**.
- Flaky leg: `[the Playwright WebKit/iPhone projection / PTY-input tests]` can wedge on the hosted runner. `timeout-minutes: [30]` caps a wedge. A wedge is a flake, not the diff.
- CI's only signal beyond the local gate is the **e2e suite** (skipped locally). Its e2e surface = `[app/webapp/, app/tray/, tests/e2e/, static assets, …]`. A diff touching **none** of these gains nothing from CI.
```

**What `/issue-finish` does with it (the shared skill mechanism, two behaviors):**
- **Skip-the-wait keyed on the e2e surface, not "docs vs code."** If the diff touches none of the project's declared e2e surface and the local gate is green → merge on local-green and **state it** in the finish summary (e.g. `CI not awaited — store-only diff, no e2e surface touched`). This generalizes the old narrow `*.md`-only skip rule into the principled one: e2e is the only thing CI adds over the local gate.
- **Proactive flake handling.** Read the expected duration from the block. While watching, the moment elapsed crosses the *investigate* threshold, stop waiting passively — inspect the run (`gh run view --job`), classify flake vs real failure, and for the *documented* flaky leg cancel + rerun **once** automatically, saying so. A second flake → stop and surface it to the user. **Never** rerun a real (non-flake) failure.

**Keep-the-human-in-control guardrails:**
- The agent always **states** its CI decision (skip vs wait, plus any rerun) in the finish summary, so the user can veto.
- Auto-rerun is capped at **once** and only for the *documented* flaky leg; a second flake stops and asks.
- Nothing force-merges. Because CI is advisory (no branch protection) no `--admin` override is ever needed. **If a repo later adds the `e2e` check as a *required* status check, the skip-rule must fall back to watching** — a required check cannot be skipped without `--admin`, and force-merging is out of scope here.

**Where each piece lives** (per the fleet "don't diverge" rule): this scaffold documents the convention + the block template; the **skill mechanism** lives in `fleet-config` `skills/issue-finish/SKILL.md` step 5 (synced to `~/.claude`); the **per-project instances** live in each project's own `CLAUDE.md` block; **sister-repo pointer issues** (start: `whatsapp-radar`, `app-launcher`) track adoption back to the canonical decision record. Making the e2e leg actually stop flaking (env-aware wait budgets / retry) is a separate per-project fix — this convention makes a flake *cheap*, it does not cure it.

## Diff-proportionate e2e routing (`.fleet.toml` `[e2e]` + `classify_e2e.py`)
*Apply only if this project has a browser e2e suite (`tests/e2e/`) wired into `verify-before-ship.*`.*

The local pre-ship gate is the contract (the section above makes CI *advisory*); this convention makes the gate's own **browser phase proportionate to the diff** instead of running the whole `tests/e2e` suite on every change. Proven in `app-launcher` (`scripts/classify_e2e.py`, #568 / PR #574 — a static-asset diff went from ~10 min to ~90 s with no loss of coverage), then promoted here **parameterized** so every web-app-shaped repo inherits the *mechanism* while declaring its own *rules*.

- **The mechanism is shared; the rules are declared per-project.** `scripts/classify_e2e.py` reads an `[e2e]` table from the repo's own `.fleet.toml` (the file that already carries the fleet-map card), so a `paths → tier` map extends the declared-paths convention rather than adding a file. TOML over a CLAUDE.md block so the classifier loads it with stdlib `tomllib` — zero custom parsing — and the rules stay versioned next to the code they classify. **`.fleet.toml` is the single auditable home for the routing table.**
- **Three tiers, worst-wins across the diff:** `skip` (every changed path is a declared `none` — backend/docs/tooling — so no browser suite runs), `static` (worst path is a declared `static` inert asset → the narrow `static_pytest_target`), `full` (any `full` path, **any unmatched path**, an empty diff, or no usable `[e2e]` table → the whole `full_pytest_target`).
- **Fail-safe is the whole point — uncertainty escalates, never narrows.** An unrecognized path, a mixed diff, a malformed/absent table all route to `full`. The table can only ever make an *already-recognized-as-narrow* diff run less; it can never make an unmatched change run less. CSS/JS route to `full` (not a curated "layout subset" — that is drift-prone and an under-testing risk); keep `static` to genuinely inert file types (images, fonts, inert vendored HTML fragments). Rules are first-match-wins, so declare specific `static` rules *before* the broader `full` prefix they sit under.
- **Wiring:** `verify-before-ship.*` runs byte-compile + the non-e2e pytest phase **unconditionally** (they already cover backend Python), then routes **only** the browser phase on the classifier's `E2E_TIER`. On CI (`$env:CI`) routing is bypassed and the full suite always runs — the local gate is where routing is proven first.
- **Anti-drift guard is mandatory.** A routing table is only safe if it stays honest as the layout grows. Two guards, both required: the `unclassified → full` fail-safe (a new, unclassified directory over-tests rather than under-tests), **and** a `tests/test_classify_e2e.py` that loads the real `.fleet.toml` and asserts representative paths land in their intended tier. When you add a new e2e-relevant directory, add its `full` rule to `.fleet.toml` **and** a representative assertion to that test in the same PR — same anti-staleness contract as the `.fleet.toml` `description` field and `docs/architecture.mmd`.
- **Don't diverge.** The convention + the parameterized `classify_e2e.py` + the `[e2e]` schema live here; the full schema reference and rule-writing guidance are in `docs/e2e-routing.md`. Web-app-shaped adopters (grocery, whatsapp-radar, family-accounting, mathgamesforkids, life-os, website, home-automation) get one-line pointer issues for follow-on adoption — not scoped here. (Decision record: `ferraroroberto/project-scaffolding#180`; source instance `ferraroroberto/app-launcher#568`.)

## End-to-end UI testing
*Apply only if this project serves a browser UI (Streamlit, FastAPI, Flask, etc.).*

Two loops, kept deliberately separate. Don't conflate them. Full reasoning, setup, and bootstrap recipe in the scaffold's `docs/playwright-ui-testing.md`.

### Iterative verification (headed, agent-driven)
Use this during active development so I can watch the agent verify a change.

- Drive the running app via the **Playwright MCP server in `--headed` mode** (Claude Code, Codex CLI). For tools without MCP support, fall back to a small `playwright` Python script run via Bash with `headless=False` — same shape, just less ergonomic.
- Boot the app **once** on a fixed port (Streamlit default: 8501) and leave it running. Do NOT restart between iterations unless `set_page_config` or top-level imports changed.
- Prefer the a11y `snapshot` tool over `screenshot` — DOM is far cheaper than pixels in tokens. Screenshot only on failure or as final visual confirmation.
- Cap actions per cycle in the prompt (≤ 5 actions, then report). Stop and ask if the page state is unexpected; do not loop blindly.
- Target widgets via their stable `key=` (already required by Streamlit conventions above) using `page.get_by_role(..., name=...)` or `page.get_by_test_id(...)`.
- Do NOT create files under `tests/e2e/` for verification — it's throwaway, lives in the conversation only. Promotion to a permanent test is a separate, deliberate decision (see below).

### Regression suite (headless, pytest-playwright)
Optional. Lives at `tests/e2e/`. **Don't create the folder until the first regression test is actually justified.**

- Add a test only when all three hold: (1) silent breakage would hurt, (2) it can't be caught by a unit test under `tests/`, (3) the behavior has stabilized (not still in flux).
- Runs via `& .\.venv\Scripts\python.exe -m pytest tests/e2e/` (Windows) / `./.venv/bin/python -m pytest tests/e2e/` (POSIX). No LLM in the loop, zero per-run cost.
- **One shared session fixture boots the app — and any service dependencies** (a separate API process, a worker, a PTY host, …) — once per pytest run. The fixture is engine-agnostic: `streamlit run`, `uvicorn`, `flask run` are all just the launch command.
- **Default to isolation — boot a disposable instance; refuse before silently adopting.** With no opt-in env var set, the fixture boots its own fresh instance and, if the target port is already occupied, **refuses** (`pytest.exit`, naming the flag) rather than killing or reusing whatever's there — a bare `pytest tests/e2e` must never silently drive a live app the harness didn't start. Opt-in to **acting on** an occupied port is **one loudly-named env var per project** (`LAUNCHER_E2E_LIVE`, this scaffold's `STREAMLIT_E2E_LIVE`) — never an opt-**out** flag (`E2E_FORCE_AUTOBOOT=1`-shaped names get the polarity backwards: forgetting to set them is what silently re-enables adoption). **What the flag permits is not the same everywhere — don't conflate the two shapes:** `app-launcher`'s `LAUNCHER_E2E_LIVE` means *read-only assertions* against the live tray, never a kill (`_require_live_tray` guard; `--e2e-autoboot` never adopts the live session-host on `:8446`, always spawns its own on a free port). This scaffold's `STREAMLIT_E2E_LIVE` means a kill-and-restart via `ensure_fresh_streamlit` — a legitimate, narrower choice specific to a stateless, cheap-to-restart dev server, and only because it goes through this repo's own canonical restart helper rather than a by-hand kill (`project-scaffolding#197`). A repo adopting the vendored guard picks its own meaning and documents it; the guard's exit message points the reader at that repo's `CLAUDE.md` rather than prescribing one. Log which instance — disposable vs. acted-on-live — the suite is driving and why, so a hung run is diagnosable from its own output. (Motivating incident: `project-scaffolding#191` — `home-automation`'s suite silently adopted the live tray with no route mocks, driving real MELCloud/RISCO/SMA/Tuya calls at ~15–20x baseline and, via ephemeral-TCP-port exhaustion, taking every fleet web app offline for minutes; audit found the same inverted opt-out polarity in `whatsapp-radar`, `voice-transcriber`, and `photo-ocr`.)
- **Isolate anything stateful — never adopt-and-mutate a host that holds the user's live work, even under the live opt-in.** The reclaim-on-opt-in rule above is safe only for a stateless, cheap-to-restart webapp (this scaffold's Streamlit process). A host that owns user state or child processes (a session-host, a worker with in-flight jobs, a PTY host) must **always** get the harness's own disposable instance on a free port, injected into the dependent process via an env override — never the live fixed port, opt-in or not. Litmus test: *is the thing I'd be touching holding work the user would be upset to lose?* If yes, isolate unconditionally. Same bar, a **destructive test scopes to what it created**: snapshot pre-existing ids before acting, kill only the delta, never `.first` / "whatever's in the list" — on a shared or adopted host that's the user's, not the test's. (Motivating incident: app-launcher#260 — a pre-ship gate adopted the live tray's session-host and its kill-tests targeted the first session in the list, repeatedly killing the user's own Coding sessions.)
- **Is a `/propagate-vendored` component: `tests/e2e/_e2e_live_guard.py` (manifest key `e2e_live_guard`).** #191 originally shipped this hand-rolled inline and reasoned it should stay prose-only because the boot/health-check mechanics differ per project shape (Streamlit subprocess vs `uvicorn` vs a session-host). #194 reversed that call: it conflated the **policy** with the **boot**. The policy — check the target port, refuse (`pytest.exit`, naming the flag) if occupied with no opt-in, otherwise log the decision — is genuinely shape-independent; only the port number, the flag name, and what happens *around* the guard (how the disposable instance actually boots) are call-site parameters. Vendored per the same pattern as `app/tray/single_instance.py` (mutex names are call-site arguments) and `tests/e2e/_geometry.py` (selectors/budgets/theme are call-site arguments) — copy the file byte-identical into an app's `tests/e2e/`, call `require_disposable_instance(port, flag_env_name)` from the fixture, and let `/propagate-vendored e2e_live_guard` hash-verify and re-vendor it fleet-wide. (`tray_lifecycle.ps1` is *not* a valid precedent here — it was de-vendored to a shared machine-local copy in #153.) The adopter records the entry in its own `.fleet.toml`'s `[vendored]` table (never here — that table lives per-adopter, not in the source repo).
- **Boot failure is a hard failure — never `pytest.skip`.** A regression suite that skips when the app isn't up reports green on a build it never tested; that is the exact rot this suite exists to prevent. Skip is fine for the *ad-hoc* "use whatever tray I have running" path; the *pre-ship* path must fail loud.
- Keep the suite small — target < 15 tests total. If you're tempted to add #20, delete two first.
- No Page Object Model. Too much ceremony for this size.
- Don't gate commits on e2e. Run on push or in CI, not in pre-commit.
- When you remove a feature, remove its e2e test in the same commit.

### Mobile / phone-first UI testing
*Apply only if the app's primary surface is a phone.*

- Project the regression suite onto **WebKit** with a device-emulation descriptor (Playwright ships iPhone / Android descriptors — viewport, user-agent, touch, scale factor). WebKit shares the iOS Safari rendering + JS engine, so it reproduces the large majority of "Safari is unhappy" bugs on a Windows/Linux box, before they reach a real phone.
- Make the projection **always-on** — a parametrised `browser_name` / device fixture so every test runs the mobile projection too. An opt-in projection gets forgotten.
- WebKit-on-Windows is *not* real iOS: no iOS shell, no real WKWebView memory limits, no Apple keyboard, no Add-to-Home-Screen container. For the residual shell-only bugs, attach PC DevTools to a real phone via `ios-webkit-debug-proxy` (bridges the iOS Web Inspector to a local port Edge/Chrome DevTools can attach to). Playwright cannot drive real iOS Safari — only its bundled WebKit and the iOS Simulator on macOS.

## Verification (before declaring a task done)
Examples — adapt to the project's actual tooling:

Windows / PowerShell:
- Syntax: `& .\.venv\Scripts\python.exe -m py_compile <file>`
- Lint (if configured): `ruff check .`
- Tests (if any exist): `& .\.venv\Scripts\python.exe -m pytest`
- Streamlit boot check (UI changes): `& .\.venv\Scripts\python.exe -m streamlit run app/app.py --server.headless true`

POSIX:
- Syntax: `./.venv/bin/python -m py_compile <file>`
- Tests: `./.venv/bin/python -m pytest`

**Pre-ship gate (projects with an e2e suite).** Once a project has a regression suite, wire a single project-specific command — e.g. `scripts/verify-before-ship.ps1` — that runs the whole pipeline as one pass/fail: byte-compile → unit `pytest` → e2e suite (auto-booting the app per the harness rule in "End-to-end UI testing"). Make it mandatory before any UI-touching change is declared done. One command, can't half-skip. Do **not** substitute a bare `pytest` run that silently skips e2e when no server is up — that is how a regression ships looking green.

## Restart and verify before hand-off
*Apply only if this project runs a long-lived process (dev server, webapp, daemon, tray) without hot-reload.*

After the verification step — and unless I said otherwise — restart that process so the change is actually live, and confirm it: check a version/build endpoint or equivalent signal that the running process reflects the new code (not just that it answers a health check — a stale process passes health checks fine). Report the build identifier. Don't hand off "done" with a stale process still serving.

**Restart safely.** Kill only the specific process for *this* app (identify it precisely — by listening port / PID / window title), never a blanket process-name kill (`pythonw`, `node`, `python`) that would also take down sibling apps or shared services on the same machine.

**A 'start' script is usually not a 'restart' script.** Re-running `launch_app.bat` / `tray.bat` / `npm start` while an instance is already up typically just spawns a duplicate (or silently no-ops if the port is bound). The pattern is **kill-then-start**, not "run start again". Document the project-specific recipe in this repo's own `CLAUDE.md` under `## This repository` — *which* process to kill (port / PID lookup), *which* command relaunches it, *what* signal confirms the new build (e.g. `GET /api/version` returning the current `git_sha`).

**A tray restart must reclaim the app's service ports by PID (orphan-proof), not just `taskkill /T` the tray subtree.** Service children (a webapp, a session-host, a tunnel) can orphan — the tray dies or is replaced while a child keeps running, leaving the subtree but still holding its port. A subtree-only kill misses it: the fresh tray can't bind, silently fails, and the orphan keeps serving stale code while the restart *reports success*.

- For each fixed loopback port the app **definitively owns**, `--restart` finds the current listener, kills its owning PID, **then** starts. Scope the sweep to **this app's `.venv`** so siblings are never touched, and exclude any **mutex-shared** port (reclaiming it would kill the sibling's live process).
- Scope by the holder's **CommandLine**, *not* its process image path: on Python 3.14 Windows venvs a venv-launched `pythonw.exe` re-execs the base interpreter, so the image path reports the *shared base* while only the CommandLine still carries the `.venv` path — an image-path guard never matches the real webapp and the reclaim silently no-ops.
- **The full detect → kill → reclaim → start → verify lifecycle lives in one committed helper, shelled to with `-File` once** — never cmd `for /f` output capture or inline `powershell -Command "…"` (`project-scaffolding#54`). Both cmd-side forms returned empty detection/reclaim data when `tray.bat` runs **non-interactively** (Git Bash → `cmd /c "tray.bat --restart"`, or a finisher skill's Bash tool), so nothing was killed and `--restart` degraded to a plain start — which **adopts** whatever already serves the port (`WebappManager.start()` → `OWNERSHIP_EXTERNAL`) and reports healthy. Only the reclaim forces new code to load.
- **Verify by served `git_sha` vs repo `HEAD`, never a `healthz` 200** (a stale adopted process passes health checks); a mismatch must exit non-zero.
- Since `project-scaffolding#153`, `tray_lifecycle.ps1` is **not** vendored per-app: every `tray.bat` calls the ONE shared, machine-local copy owned by `fleet-config` at `%USERPROFILE%/.claude/tray/tray_lifecycle.ps1` (exposed by its `install.ps1` junction). `tray.bat` still hard-errors (never no-ops) if that path is missing, naming fleet-config's `install.ps1` as the fix. A tray app still vendors `app/tray/single_instance.py` byte-for-byte — it ships *with* the app rather than being shelled to.

This is the third tray-lifecycle gotcha, alongside **#12** (single-instance via a named mutex, not a bound TCP port) and **#13** (`CREATE_NO_WINDOW` when shelling out to console tools); it does not conflict with #12 — #12 *detects* a running instance, this is how a *restart cleans up* the previous one. Canonical `tray.bat` shape (idempotent start + verified reclaim-then-start) and full reasoning: `docs/windows-tray.md`; a copy-to-adapt `tray.bat.template` ships at the scaffold root (replace four `__PLACEHOLDER__` tokens — app name, tray-launch args, tray-match regex, owned ports).

**The canonical restart invocation is `tray.bat --restart` — call it, don't hand-roll the kill.** Once a project ships a `tray.bat` with `--restart`, that one command *is* the restart: it does the orphan-proof subtree-kill + per-`.venv` port reclaim + start atomically. Automated finishers (`/issue-finish`, `/issue-yolo`) and any agent restart must run `tray.bat --restart` rather than re-deriving a `Get-NetTCPConnection`/`taskkill` sequence by hand — a hand-rolled kill only catches the one listener it happens to find and misses the orphan the reclaim sweep exists to kill. The manual port-PID kill is a *fallback* for the rare app that has no `--restart`, never the default. Each tray app's own `CLAUDE.md` `## This repository` section names `tray.bat --restart` as its restart command plus the signal that confirms the new build is live.

**A tray's single-instance guard must hold *in the tray process* (a named mutex), and its adopt-or-spawn must be *race-safe*.** This is the **fourth** tray-lifecycle gotcha, alongside **#12** / **#13** / **#29** above. The launcher `.bat`'s pre-launch CIM detection is necessary but not sufficient — two near-simultaneous `tray.bat` runs both read the process table before either tray is visible, pass the check, and both survive; per #12 the guarantee belongs to a named mutex the tray holds for its lifetime (acquire at the top of `run_tray()`; if already held, exit). Independently, a `WebappManager.start()` that does `status()`-then-`Popen` is check-then-act: two trays that both see "port free" both spawn a duplicate uvicorn (a TOCTOU race). Serialize the check-then-spawn with a named mutex keyed on the owned port so the loser **adopts** the now-listening service instead of spawning. Both are solved by one byte-identical primitive — `app/tray/single_instance.py` (`SingleInstance` + `cross_process_lock`) — shipped in the scaffold and **vendored verbatim** (only the mutex *names* differ per app). Proven on `whatsapp-radar`: one clean `tray.bat` spawned two trays + two uvicorns contending for one port. Full reasoning in the scaffold's `docs/windows-tray.md` (gotcha #4).

**The agent restarts a tray by invoking `tray.bat --restart` fire-and-forget, then verifying with a *bounded* poll — never a foreground launch or an unbounded wait.** A tray launcher holds the console it starts in, so a foreground tool call never returns and burns the 10-minute timeout (where the historical restart hangs lived). Call `--restart` non-blocking (background/detached) so the tool returns at once, then poll `GET /api/version` with a **hard timeout and attempt cap** (e.g. ≤30 s), asserting `git_sha == HEAD` and reporting the build line; **fail loud** on a slow/failed boot. A `/healthz` 200 is not enough — a stale process passes it. The app's `--restart` owns the what-to-kill/reclaim intelligence (ports, children), so the agent delegates rather than re-derives.

A correct restart is **adopt / reclaim / spawn** — re-attach to healthy owned children, reclaim stale port-holders, spawn only what's missing — classifying children as **owned-and-cycled** (webapp/worker/cloudflared: live *inside* the tray subtree, die + respawn with new code, port in the reclaim list) vs **linked-but-independent** (a session-host + its PTY shells / launched apps: must **survive**). "Must survive" is enforced structurally, not by a warning: linked children are **spawned re-parented out of the tray subtree** via `cmd /c start` — `taskkill /T` walks the parent-child PID tree, so `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP` do **not** escape it; only re-parenting does (verified empirically) — and the fresh tray **re-adopts** them on start by port/identity. That is what makes the one canonical `tray.bat --restart` safe everywhere, including from *inside* a session the tray's session-host is hosting. **Safety caveat:** until a tray with linked children is detach-compliant, `--restart` still kills those children — that tray's `CLAUDE.md` flags this and the agent confirms first. Mirrored in the `/issue-finish` finisher and the global restart skill (`project-scaffolding#35`).

**Propagation freeze — a vendored-component fix does not fan out until this repo's own gate is green, and a second same-day bug in the same component freezes it entirely.** This repo vendors one channel verbatim into every sister repo that needs it: the web-app UI components (`app/webapp/static/_vendored/`) and, for tray apps, the imported `app/tray/single_instance.py` primitive. (`tray_lifecycle.ps1` left this model in `#153` — machine-local infrastructure, not app code; ownership story in `docs/windows-tray.md`, channel rule "does it ship with the app?" in `app/webapp/static/_vendored/README.md`.)

- A vendored-component fix does **not** propagate until this scaffold's own verification gate is green — for the tray helper that includes the behavioral e2e harness `tests/e2e/test_tray_lifecycle_behavior.py`, which drives the real lifecycle end to end against the canonical file (resolved via `resolve_tray_lifecycle_path()`), not just structural/grep asserts.
- A **second** bug in the same vendored component **within the same day** freezes propagation entirely — harden and soak at source, no partial re-vendor, then ship one cumulative wave once stable.
- UI-component propagation is never a hand-filed per-repo issue; trigger criteria for the batched `/propagate-vendored` run live in `app/webapp/static/_vendored/README.md` ("Rules").

(Motivating incident: the 2026-07-09/10 tray cascade, `#144` → `#145`/`#146` → `#147`/`#148` → `#149`/`#150` — four defect waves in 48 hours, each reproducible at source with no sister repo involved, each discovered only *after* fanning out to ~6 trays and ~22 mechanical PRs.)

---

## This repository
Starter scaffold for a Streamlit app + Python pipelines project — clone, rename, and build.
See `README.md` for setup, layout, and usage.

### Internal architecture

[`docs/architecture.mmd`](docs/architecture.mmd) is a hand-authored Mermaid diagram of this repo's own internal structure (`app/`, `src/`, `scripts/`, `tests/`, `docs/`, external dependencies). Update it in the same PR as any material structural change (a new view, a new vendored component, a script relocated) — same anti-staleness contract as this repo's own `.fleet.toml` `description` field. It is hand-authored, not auto-generated, and not covered by `scripts/verify-before-ship.ps1`.

Standing up a new self-hosted **PWA** app (FastAPI + static PWA + Windows tray)? `docs/app-onboarding.md` is the canonical end-to-end playbook — bootstrap the app, issue + trust the self-signed-CA HTTPS cert (the exact `certutil -user -addstore Root ca.pem` command + the full-Chrome-restart gotcha + the leaf-cert expiry note), and install the PWA on an iPhone (the `/install-ca` mobileconfig detour) / Android. It cross-links `docs/windows-tray.md` for the tray lifecycle rather than duplicating it.
