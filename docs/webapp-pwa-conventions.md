# Webapp PWA conventions

Moved verbatim from `CLAUDE.md` (`#254`) so the always-on file stays under its size cap. `CLAUDE.md` keeps each section's heading, its *apply only if* gate and one-line rules, and points here for the full procedure, reasoning, snippets and decision records. Headings match `CLAUDE.md`'s, so a reference to a section by name resolves in either file.

## UX surface — diff-keyed design-conformance gate *(PWA)*

**Two checks, kept separate — a real gate uses both, scoped to the diff.** *Token check* (`/design-sync`-style): diffs CSS custom properties (light+dark) and the nav contract vs spec; static, no browser, never renders — catches "accent drifted", misses "nav pushed off-screen / cards overlap". *Visual verification* (`verify`-style): launches the live app, drives the touched view in a headed browser, screenshots it — the only check that *sees* the result; the token-expensive leg.

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
