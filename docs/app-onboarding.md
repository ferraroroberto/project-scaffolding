# New self-hosted PWA app: onboarding playbook (didactic)

Personal reference for standing up a **new tray-resident FastAPI + static PWA app** from this scaffold, end to end, until it is reachable as a trusted-HTTPS installed PWA on an iPhone. It collects three procedures that every fleet app (`home-automation`, `photo-ocr`, `app-launcher`, …) has otherwise rediscovered independently: bootstrap the app, provision HTTPS (a real Let's Encrypt cert via `tailscale cert` for a tailnet app — preferred, zero per-device trust; the self-signed-CA dance only as the LAN-only fallback), and install the PWA on a phone. The per-app README instances stay; this is the canonical *procedure* so the knowledge stops drifting and a new app doesn't re-pay the discovery cost.

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

## See also

- [`windows-tray.md`](windows-tray.md) — the tray lifecycle this playbook deliberately does **not** duplicate: idempotent single-instance start, the orphan-proof `tray.bat --restart`, and the agent-side restart contract.
- `home-automation` `README.md` (the cert + "Phone install (PWA)" sections) and `photo-ocr` `README.md` — the two worked examples this playbook is lifted from.
- `scripts/gen_tailscale_cert.py` (this scaffold) — the preferred-path generator: provision a real Let's Encrypt leaf via `tailscale cert` plus the `--check` auto-renew leg. Reference wire-up into a webapp launcher: `grocery-shopping-automation`'s `webapp.bat`.
- `scripts/gen_ssl_cert.py` in either worked-example repo — the **fallback** self-signed CA + leaf generator (auto-trust on Windows, `/install-ca` mobileconfig output) for LAN-only apps.
