# New self-hosted PWA app: onboarding playbook (didactic)

Personal reference for standing up a **new tray-resident FastAPI + static PWA app** from this scaffold, end to end, until it is reachable as a trusted-HTTPS installed PWA on an iPhone. It collects three procedures that every fleet app (`home-automation`, `photo-ocr`, `app-launcher`, …) has otherwise rediscovered independently: bootstrap the app, provision HTTPS (a real Let's Encrypt cert via `tailscale cert` for a tailnet app — preferred, zero per-device trust; the self-signed-CA dance only as the LAN-only fallback), and install the PWA on a phone. The per-app README instances stay; this is the canonical *procedure* so the knowledge stops drifting and a new app doesn't re-pay the discovery cost. §4 then carries the two webapp-shape internals worth getting right once the app is reachable — static-asset cache-busting and the SQLite connection lifecycle.

> **Audience.** Me, plus any AI coding agent I hand a fresh app to.
> **Status.** Living reference, not a changelog. Update in place when the recipe changes.
> **Worked examples.** `home-automation` (the cert + "Phone install (PWA)" README sections) and `photo-ocr` are the two apps this playbook is lifted from — open either repo's `README.md` + `scripts/gen_ssl_cert.py` for a filled-in instance.
> **Scope.** The cold-handoff test for this doc: a fresh reader takes a scaffold clone to a trusted-HTTPS, iPhone-installed PWA using only what is written here. The tray *lifecycle* (idempotent start, orphan-proof `--restart`) is **not** re-documented — it lives once in [`windows-tray.md`](windows-tray.md) and this doc links to it. Cloudflare-tunnel / public remote access is a separate concern and out of scope.

---

## 1. Stand up a new app from the scaffold

Clone this scaffold, rename the directory, and wire the basics. The scaffold ships a Streamlit POC surface plus the FastAPI + PWA and tray primitives; a self-hosted PWA app keeps the latter and builds its product under `app/webapp/`.

```powershell
# Clone + rename (the scaffold is the template; the new app is a separate repo)
git clone <scaffold-url> E:\automation\my-new-app
cd E:\automation\my-new-app

# Create the virtual environment. ALWAYS .venv, NEVER venv. Never activate it in
# scripts — invoke the interpreter directly (& .\.venv\Scripts\python.exe ...).
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Config + secrets. .env is the SECRETS file; .venv is the virtualenv DIR — never
# conflate the two. Copy the examples to real files (the reals are gitignored).
copy .env.example .env                       # then fill in secrets
copy config\*.sample.json config\            # then rename each to its real name
```

Set this app's identity before anything else: update `.fleet.toml` (its architecture-map card — replace the scaffold's placeholder values with this repo's `layer` / `icon` / `description` / `port`), and update `README.md` + `CLAUDE.md` for the new app's name and shape.

**Tray + long-lived service.** A self-hosted PWA app runs its webapp under a Windows tray that owns the service port. Do **not** re-derive the tray lifecycle here — copy `tray.bat.template` → `tray.bat` (replace the four `__PLACEHOLDER__` tokens), and vendor the two helpers verbatim (`app/tray/tray_lifecycle.ps1`, `app/tray/single_instance.py`). The full reasoning — idempotent single-instance start, the orphan-proof `tray.bat --restart` that reclaims owned ports by PID, and the agent-side bounded-poll restart contract — lives in [`windows-tray.md`](windows-tray.md). Read that before writing or fixing the restart; this playbook assumes the tray is already wired per that doc.

**Launch (foreground / dev).** Before the tray exists, run the webapp directly to confirm it boots. The webapp serves HTTPS once `webapp/certificates/cert.pem` exists (section 2 below), otherwise plain HTTP:

```powershell
& .\.venv\Scripts\python.exe -m uvicorn app.webapp.server:app --host 0.0.0.0 --port <PORT> `
    --ssl-keyfile webapp/certificates/key.pem --ssl-certfile webapp/certificates/cert.pem
```

The signal that the new code is actually live is a product-specific render (e.g. the card grid populating), **not** a `/healthz` 200 — a stale process answers health checks fine. Pick that signal per app and write it into the app's own `CLAUDE.md` `## This repository`.

**Pin the selector event loop — every uvicorn spawn, from the first boot.** On Windows, asyncio's default **proactor** event loop closes its listening socket the moment `accept()` raises any `OSError` (CPython's `proactor_events.py:_start_serving` accept loop) — a client aborting a connection mid-handshake (a browser dropping the socket, a phone roaming off Wi-Fi) surfaces as exactly such an error (`WinError 64`), and one aborted client wedges the listener: the process stays alive but every subsequent connection fails until a manual restart. The **selector** event loop has no such failure mode. Fixed in `app-launcher#388` after the bug wedged its phone-facing webapp; verified empirically there that a bare `SelectorEventLoop` server survived 800 concurrent aborted connections while a `ProactorEventLoop` server died after ~20.

Copy `app-launcher`'s `app/webapp/event_loop.py` (`selector_loop_factory`) verbatim into a new app's `app/webapp/` and wire it into **every** uvicorn spawn point via `--loop`/`loop=`:

```python
# app/webapp/event_loop.py — must return an instantiated loop, not a loop class:
# uvicorn imports a custom --loop/loop= dotted-path target and calls it directly
# as the final zero-arg factory (no use_subprocess= indirection like its
# built-in names get).
def selector_loop_factory() -> asyncio.AbstractEventLoop:
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
```

```powershell
# CLI invocation (webapp.bat, WebappManager._build_command, e2e autoboot spawn):
--loop app.webapp.event_loop:selector_loop_factory
```

```python
# programmatic uvicorn.run() (e.g. app/cli/commands/webapp_cmd.py):
uvicorn.run(..., loop="app.webapp.event_loop:selector_loop_factory")
```

Do this at scaffold time, not after the first phone-roaming wedge — see the `CLAUDE.md` rule under the webapp/PWA conventions.

---

## 2. Provision HTTPS — `tailscale cert` (preferred) or self-signed CA (LAN-only fallback)

An installed PWA needs HTTPS (Service Workers + Web Push are HTTPS-only), and a phone reaching the webapp needs a cert whose chain the phone trusts. There are two ways to get one, and the right one depends on **how the app is reached remotely**:

- **Reached over Tailscale → `tailscale cert` (§2a, preferred).** A real Let's Encrypt leaf for the tailnet MagicDNS name, trusted by every device on the tailnet with **zero** per-device steps. The default for any tailnet-reachable app.
- **LAN-only / no Tailscale → self-signed CA (§2b, fallback).** Mint a local CA + leaf and trust the CA once on every device. The only option without a tailnet, and it carries the per-device trust dance in §3.

### 2a. Tailscale cert (preferred — zero per-device trust)

`tailscale cert <host>.ts.net` issues a **real Let's Encrypt certificate** for the tailnet MagicDNS name. Tailscale owns the `ts.net` domain and answers the ACME DNS-01 challenge for it, so there is **no public DNS name, no HTTP-01/DNS-01 setup, and no inbound exposure** on your side. Every device already on the tailnet already trusts Let's Encrypt, so there are **no per-device trust steps at all** — no CA install, no `.mobileconfig`, no Certificate-Trust toggle, no Chrome-restart gotcha. This is *simpler* than the self-signed dance, not overkill (see the note at the end of §3).

**One-time prereq (once per tailnet).** Enable HTTPS certificates in the Tailscale admin console: <https://login.tailscale.com/admin/dns> → "HTTPS Certificates" → **Enable**. That is the entire setup.

```powershell
& .\.venv\Scripts\python.exe scripts\gen_tailscale_cert.py
```

The generator auto-detects this machine's MagicDNS name from `tailscale status --json`, runs `tailscale cert`, and writes `cert.pem` / `key.pem` into `webapp/certificates/` — the same dir the launcher passes to uvicorn (section 1). Pass an explicit hostname (`gen_tailscale_cert.py tower.tail1121fd.ts.net`) to override the auto-detect.

> **Auto-renew on startup is mandatory, not optional.** The Let's Encrypt leaf is **~90 days** — far shorter than a self-signed root's 10 years — so a manual re-issue *will* eventually be forgotten and the app *will* one day serve an expired cert. The generator ships a `--check` mode that renews the cert **only** if it is a `.ts.net` leaf expiring within ~30 days; it **no-ops a self-signed cert** and never blocks startup on an error. Wire `--check` into the app's own webapp launcher so a stale cert self-heals on the next boot, **before uvicorn binds**:
>
> ```bat
> REM In the app's own webapp launcher (e.g. webapp.bat), before the uvicorn line:
> "%VENV_PY%" "%SCRIPT_DIR%scripts\gen_tailscale_cert.py" --check
> ```
>
> Put this in the **app's own launcher**, not the generic `tray.bat.template` — that template is the byte-identical vendored tray lifecycle, and cert provisioning is app-specific. The reference wire-up lives in `grocery-shopping-automation`'s `webapp.bat`.

`localhost` is **not** covered by this cert (the leaf is issued only for the `.ts.net` name), so `https://localhost:<PORT>` shows a hostname-mismatch warning — use `http://localhost:<PORT>` for plain local desktop access and the `https://<host>.ts.net:<PORT>` URL everywhere else.

### 2b. Self-signed CA (LAN-only / no-Tailscale fallback)

Use this **only** for an app with no tailnet access — a genuinely LAN-only / loopback-only surface. It mints its own local **CA + leaf** and requires trusting the CA once on **every** device (the dance in §3). The app mints the CA + leaf with `scripts/gen_ssl_cert.py` (derive it from a worked example — `home-automation` / `photo-ocr` — if the scaffold itself doesn't ship one yet; that's tracked as a separate concern). The leaf's SAN list auto-includes loopback (`127.0.0.1`, `::1`, `localhost`), the machine hostname, and bound LAN IPv4s.

```powershell
& .\.venv\Scripts\python.exe scripts\gen_ssl_cert.py
```

Output lands in `webapp/certificates/`: `ca.pem` / `ca.key` (the local CA) and `cert.pem` / `key.pem` (the leaf the webapp serves). On Windows the script *also* auto-installs `ca.pem` into the per-user trust store so Edge/Chrome on this PC trust it without admin — equivalent to running the command below. Pass `--skip-install` to mint the cert without touching the trust store.

**Trust the CA on this Windows PC (manual fallback).** If you used `--skip-install`, or the auto-install didn't take, install the CA into the per-user Root store by hand. This needs **no admin** — it is the `CurrentUser\Root` store, not the machine store:

```powershell
certutil -user -addstore Root webapp\certificates\ca.pem
```

**Gotcha — fully restart Chrome to pick up a new root.** Chrome and Edge on Windows read `CurrentUser\Root`, but they cache the trust set at startup and only re-read it after a **full** restart — every window closed, not just the tab or a single window. After trusting (or re-trusting) the CA, quit the browser completely and reopen, or you'll keep seeing `NET::ERR_CERT_AUTHORITY_INVALID` on `https://127.0.0.1:<PORT>` against a CA that *is* now trusted. This single step is the one most often missed when bringing a self-signed app up.

> **Leaf-cert expiry / re-issue.** The leaf is capped at ~395 days because Apple/WebKit reject server certs valid > 398 days. After ~13 months Safari shows "Not Secure" and Chrome flags the cert as expired — that is the **leaf expiring, not a regression**. Re-run `gen_ssl_cert.py`: it **reuses the existing CA** (the long-lived, 10-year root), so it only re-mints the leaf — already-trusted devices (the PC, every phone) do **not** need to re-trust anything. Just regenerate and restart the webapp. (A fresh CA — `--force-new-ca` — *would* force every device to re-trust; you only want that if the CA key is compromised.) Note the renewal deadline in the app's own README, not in memory.

---

## 3. iPhone / Android PWA install

The webapp installs to the phone home screen as a full-screen app. **If you provisioned the cert with `tailscale cert` (§2a), there is nothing to trust** — the phone already trusts Let's Encrypt — so skip straight to "Add to Home Screen" below. The CA-trust detour applies **only** to the self-signed fallback (§2b).

**Install the PWA (any cert):**

- **iOS (Safari):** open `https://<host>.ts.net:<PORT>` (Tailscale) or the LAN URL, then **Share → Add to Home Screen**.
- **Android (Chrome):** **Install app** directly from the page menu.

**Self-signed fallback only (§2b) — one-time iOS CA trust before install:** because the cert is signed by a **self-signed CA the phone has never seen**, iOS will not trust it until the CA is installed *and* explicitly trusted, via a configuration profile (a `.mobileconfig`) the server hands out at `/install-ca`.

1. In Safari, open the dashboard, expand **Settings**, and tap **Install certificate** — or open `https://<pc-hostname>:<PORT>/install-ca` directly. Tap **Allow** to download the configuration profile.
2. **Settings → General → VPN & Device Management** → tap the downloaded profile → **Install** (enter your passcode).
3. **Settings → General → About → Certificate Trust Settings** → toggle full trust **ON** for the app's CA (e.g. "Home Automation Local CA"). This step is separate from installing the profile and is easy to miss — without it the cert is installed but still untrusted.
4. Force-quit Safari and reopen the URL. The lock icon should now be solid. Then **Share → Add to Home Screen** to install the PWA.

**Self-signed fallback only (§2b) — Android:** the CA is served as DER at `/static/ca.crt` if a device needs the root installed.

> **Why the self-signed path forces a per-device detour — and why Tailscale avoids it.** iOS only trusts server certs that chain to a CA in its trust store, and a self-signed local CA isn't there by default, so the fallback needs the one-time profile-install + Certificate-Trust toggle on every device. A public CA avoids it — and for a **tailnet** app `tailscale cert` *is* that public CA with **none** of the usual cost: Tailscale owns `ts.net` and answers the ACME challenge, so there is no public DNS name to register and no reachable HTTP-01/DNS-01 validation to set up. That is why §2a is preferred and this detour is the LAN-only fallback, not the default. (This corrects earlier guidance that called a public CA "overkill for a loopback/tailnet-only app" — true for a genuinely loopback-only app, wrong for a tailnet one.)

---

## 4. App internals worth getting right — cache-busting + the DB connection

Once the app boots over HTTPS (§1–§3), two webapp-shape conventions decide whether it behaves under load. Both have been re-derived (or forgotten) per app and are now canonical — the scaffold `CLAUDE.md` records the rule; this section carries the reference snippets so a new app copies one thing.

### 4a. Cache-bust the static module graph (`CachingStaticFiles` + fleet hash)

A bare `StaticFiles` mount sends only `ETag`/`Last-Modified`, so an installed iOS PWA heuristic-caches the JS/CSS and keeps running the **old build** after a deploy + tray restart — while `/api/version` reports the new SHA. The fix is a single content/build hash used as the asset cache key, plus an explicit per-suffix `Cache-Control` and a shell that always revalidates. The nominated canonical implementation is `home-automation/src/static_versioning.py` (the `BuildInfo` + fleet-hash + rewriters) and the `CachingStaticFiles` subclass in `home-automation/app/webapp/server.py`. Copy those; adapt only the static dir.

**Why a *fleet* hash, not a per-file hash.** The webapp is an ES-module graph — `index.html` loads `main.js`, which imports the other modules. A naive per-file hash goes stale on a transitive edit: if `state.js` changes but `main.js`'s own bytes don't, `main.js`'s hash is unchanged, yet the graph it pulls in is now different — so the device re-fetches `main.js` (unchanged) and keeps the stale `state.js`. A single **fleet hash** — one SHA-256 over the concatenation of every hashable file's per-file hash — rotates *every* `?v=` stamp on any edit to any module, so the whole (tiny) graph is re-fetched together:

```python
# static_versioning.py — the fleet hash (one value stamped onto every asset)
def compute_asset_hashes(static_dir: Path) -> Dict[str, str]:
    """Return {filename: fleet_hash} for every hashable static file.

    Every value is the SAME fleet hash, so any edit to any module rotates
    every ?v= stamp. Keyed by filename only so a rewriter can confirm a
    referenced file exists before stamping. Empty dict on a partial deploy
    → unstamped URLs rather than a crashed page.
    """
    if not static_dir.exists():
        return {}
    per_file = {p.name: _short_hash(p.read_bytes()) for p in _iter_hashable_files(static_dir)}
    if not per_file:
        return {}
    fleet_input = "\n".join(f"{n}:{per_file[n]}" for n in sorted(per_file)).encode("utf-8")
    fleet_hash = _short_hash(fleet_input)
    return {name: fleet_hash for name in per_file}
```

The rewriters stamp `?v=<fleet_hash>` onto each `href`/`src` in `index.html` (`rewrite_index_html`, wrapped by `BuildInfo.stamp_html`) and onto each relative `import` in a served `.js` (`rewrite_js_imports`, wrapped by `BuildInfo.stamp_js`). **Canonical names are `stamp_html` / `stamp_js`** — this is the resolution of the old photo-ocr `stamp_js` vs voice-transcriber `rewrite_js_imports` split: apps copy one API. The matching regexes also capture an existing `?v=…` so re-stamping an already-served body is idempotent.

**Per-suffix `Cache-Control`, and a shell that always revalidates.** The mount subclass keys the policy on the file suffix; the root route serves the shell `no-cache` so the entry document re-validates every load (a cached shell pointing at the old entry module would defeat the hashing):

```python
# server.py — CachingStaticFiles: hash-stamped assets cache hard, shell revalidates
_LONG_CACHE = "public, max-age=31536000, immutable"   # .js / .css — fleet hash is the cache key
_DAY_CACHE = "public, max-age=86400"                  # manifest / icons — rarely change

class CachingStaticFiles(StaticFiles):
    def file_response(self, full_path, stat_result, scope, status_code=200) -> Response:
        path = Path(full_path); suffix = path.suffix.lower()
        if suffix == ".js":
            try:
                body = path.read_text(encoding="utf-8")
            except OSError:
                return super().file_response(full_path, stat_result, scope, status_code)
            return Response(BUILD_INFO.stamp_js(body), status_code=status_code,
                            media_type="text/javascript", headers={"Cache-Control": _LONG_CACHE})
        response = super().file_response(full_path, stat_result, scope, status_code)
        if suffix in {".js", ".css"}:
            response.headers["Cache-Control"] = _LONG_CACHE
        elif suffix in {".webmanifest", ".png", ".ico"}:
            response.headers["Cache-Control"] = _DAY_CACHE
        return response

# The shell (index.html root route) — stamp asset URLs, force revalidation:
@router.get("/")
async def index() -> HTMLResponse:
    html = BUILD_INFO.stamp_html((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})
```

`BuildInfo` (computed once at startup) also surfaces `{git_sha, built_at, asset_hash}` at `/api/version` and the glanceable `Build:` footer (§the required-surfaces convention in `CLAUDE.md`); its git-SHA capture is console-less-tray-safe (`CREATE_NO_WINDOW` + `stdin=DEVNULL`). Verify with `curl -I` — `.js`/`.css` carry the long-immutable header, `/` carries `no-cache` — and confirm a real mobile PWA picks up new JS on a **normal reload** after a deploy, no delete/re-add. Service workers / offline caching are deliberately not used in the fleet.

### 4b. One SQLite connection per request via a `Depends` dependency

A FastAPI app backed by SQLite exposes the connection through **one** dependency that opens it, `yield`s it, and closes it in a `finally`. One place owns open/close and the connection setup (pragmas, row factory, timeout); every handler that needs the DB just declares `Depends(get_db)`, and the handle is guaranteed closed even when the handler raises. This replaces the per-handler `connect → use → close` boilerplate that `whatsapp-radar` had copy-pasted across 11 handlers (`ferraroroberto/whatsapp-radar#100`) — every copy a potential leak on an early return, all of them needing edits together to change setup.

```python
import sqlite3
from typing import Iterator
from fastapi import Depends

def get_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()

# Every handler takes the connection by dependency — never opens its own:
@router.get("/messages")
async def list_messages(db: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM messages ORDER BY ts DESC LIMIT 100")]
```

Acceptance: a derived app has **zero** per-handler `sqlite3.connect(...)` calls in its routers. SQLite + stdlib `sqlite3` stays the fleet default — this is only the lifecycle dependency, not an ORM / async driver / connection pool. The documented exception (none currently in the fleet) is an app that legitimately needs a long-lived single connection.

Two gotchas when first adopting this (both surfaced shipping it into `whatsapp-radar`):

- **ruff B008.** `Depends(get_db)` as a default argument is FastAPI's documented idiom, but `flake8-bugbear`'s B008 ("do not perform function calls in argument defaults") flags every injection. Add `fastapi.Depends` to ruff's `flake8-bugbear.extend-immutable-calls` allowlist in `pyproject.toml` so the convention doesn't fight the linter.
- **async handlers → `async def` dependency.** If your handlers are `async def`, make `get_db` an **`async def` generator**. A plain `def` generator runs in Starlette's threadpool while the handler runs on the event-loop thread, so the connection is created in one thread and used in another — `sqlite3`'s same-thread guard trips unless you pass `check_same_thread=False` (the snippet above does). The `async def` form keeps creation and use on the same thread and is the cleaner fix.

---

## See also

- [`windows-tray.md`](windows-tray.md) — the tray lifecycle this playbook deliberately does **not** duplicate: idempotent single-instance start, the orphan-proof `tray.bat --restart`, and the agent-side restart contract.
- `home-automation` `README.md` (the cert + "Phone install (PWA)" sections) and `photo-ocr` `README.md` — the two worked examples this playbook is lifted from.
- `scripts/gen_tailscale_cert.py` (this scaffold) — the preferred-path generator: provision a real Let's Encrypt leaf via `tailscale cert` plus the `--check` auto-renew leg. Reference wire-up into a webapp launcher: `grocery-shopping-automation`'s `webapp.bat`.
- `scripts/gen_ssl_cert.py` in either worked-example repo — the **fallback** self-signed CA + leaf generator (auto-trust on Windows, `/install-ca` mobileconfig output) for LAN-only apps.
- `home-automation/src/static_versioning.py` + the `CachingStaticFiles` subclass in `home-automation/app/webapp/server.py` — the nominated **canonical** cache-busting reference (§4a): the fleet-hash `BuildInfo` with `stamp_html`/`stamp_js`, copied verbatim into a new PWA app.
- `ferraroroberto/whatsapp-radar#100` — the 11-handler `sqlite3.connect` boilerplate that motivated the one-`get_db`-`Depends` convention (§4b).
