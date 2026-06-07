# Robust Windows tray: idempotent start + orphan-proof restart (didactic)

Personal reference for projects that ship a **Windows tray app owning a long-lived service** (a uvicorn webapp, a PTY session-host, a cloudflared tunnel) launched on login. Captures the *mental model* and the canonical `tray.bat` shape that keeps a restart from silently serving stale code. Sister-app trays (`app-launcher`, `photo-ocr`, `voice-transcriber`) derive from this.

> **Audience.** Me, plus any AI coding agent I hand a project to.
> **Status.** Living reference, not a changelog. Update in place when the recipe changes.
> **Canonical record.** [`project-scaffolding#29`](https://github.com/ferraroroberto/project-scaffolding/issues/29). Sits alongside the two other tray-lifecycle gotchas: **#12** (single-instance via a named mutex, not a bound TCP port) and **#13** (`CREATE_NO_WINDOW` when shelling out to console tools).

---

## TL;DR

- A `start` script is not a `restart` script. Re-running `tray.bat` while an instance is up just spawns a duplicate (or silently no-ops once a port is bound). The pattern is **kill-then-start**, never "run start again".
- A restart must **not** assume the old instance's service-bound children are still in the tray's process subtree. They can orphan. `taskkill /T /PID <tray>` alone misses an orphan, the fresh tray can't bind the port, and the old orphan keeps serving stale code while the restart *reports success*.
- The reliable mechanism is a **port-reclaim sweep**: for each fixed loopback port the app owns, find the current listener and kill its owning PID, scoped to **this app's `.venv`**, *then* start.
- Scope the sweep by the holder's **CommandLine**, not its process image path. On Python 3.14 Windows venvs a venv-launched `pythonw.exe` re-execs the base interpreter, so the process image path reports the *shared base* interpreter — only the CommandLine still carries the `.venv` path. A path-based guard never matches the real webapp and the reclaim silently no-ops.

---

## The mental model

A tray app owns a small constellation of processes: itself (the tray icon), plus the services it spawns — a webapp on a fixed loopback port, maybe a session-host on another, maybe a cloudflared tunnel. The tray is the parent; the services are its children.

Two facts make a naive restart unsafe:

1. **Children can outlive (or detach from) their parent.** The tray process can die, be replaced, or be killed while a child keeps running. That child is now an *orphan* — still bound to its service port, no longer in any tray's process subtree. A subtree kill (`taskkill /T /PID <tray>`) cannot reach it.
2. **A second bind silently fails.** When the fresh tray spawns a new webapp, the new process tries to bind the same fixed port, the OS refuses (the orphan still holds it), and depending on framing the failure is swallowed. The phone keeps talking to the *orphan* — the old build — and the restart looks like it worked.

So a correct restart cleans up by **port ownership**, not by process parentage. For every port the app definitively owns, reclaim it by PID, then start fresh.

## The rule

`tray.bat --restart` = **(1) reclaim each owned service port by PID** (orphan-proof) → **(2) start**. Plus, belt-and-braces, keep the existing tray-PID-subtree kill for non-port children like cloudflared.

1. **Detect the running tray** by CIM on command line + this repo's `.venv` path (idempotency guard for the no-arg start). Match the tray's own invocation (`launcher.py tray` or equivalent), never a bound port — that is gotcha #12's job.
2. **On `--restart`, kill the tray subtree by PID** (`taskkill /T /F /PID <tray>`), so cloudflared and any non-port children go down with it.
3. **Then reclaim each owned service port.** For each fixed port the app owns, find the listener's `OwningProcess`, and kill it **only if its CommandLine is under this repo's `.venv`**. This catches an orphan that the subtree kill missed.
4. **Wait briefly** for Windows to release the ports (a short `ping 127.0.0.1 -n 3` loopback delay), then start.

### Scope by CommandLine, not image path (the correction that matters)

The obvious scope guard — "only match the process if its *image path* is under `<app>\.venv`" — is **wrong on modern Windows venvs** and was corrected out of the canonical form. On Python 3.14, a venv-launched `pythonw.exe` re-execs the *base* interpreter, so a running tray/webapp/session-host reports the **shared base interpreter** as its image path (`Get-Process.Path` / `Win32_Process.ExecutablePath` = `…\pythoncore-3.14-64\pythonw.exe`), not the repo's `.venv`. Only the process **CommandLine** still carries the `.venv` path (it's how the venv launcher invoked it). An image-path guard therefore *never matches the real process*, the operation silently no-ops, and you get back the exact "reports success, changes nothing" failure the convention exists to prevent.

This applies to **both** uses of the per-app match: the `--restart` **port-reclaim** (which holder to kill) **and** the single-instance **detection** (is a tray already running?). The original 2026-06-04 correction fixed only the reclaim block; the detection block kept an `ExecutablePath.StartsWith(...)` guard and so never recognised a live tray on a pythoncore venv — every `tray.bat` invocation then stacked another tray and the webapp port deadlocked. Both blocks now match on CommandLine.

Match on `CommandLine` containing the repo's `.venv` path (ordinal, case-insensitive). That uniquely identifies *this* app's processes while leaving sibling apps' processes (and unrelated processes that merely happen to hold the port) untouched.

### Only reclaim ports the tray definitively owns

A port that is **mutex-shared with another app** must **not** go in the reclaim list. Example: an audio/whisper port (`:8090`) shared between a voice-transcriber tray and the local-LLM hub. Reclaiming a shared port would kill the *other* app's legitimately-running process. List only the ports this tray exclusively owns (its own webapp / session-host). Shared ports are coordinated by mutex, not reclaimed.

## Platform gotcha (Windows / PowerShell 5.1)

- `tray.bat` shells out to **Windows PowerShell 5.1** (`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`). Keep the inline PowerShell **ASCII-only** — a stray em-dash or other non-ASCII char in a `.ps1`/inline command breaks PS 5.1 parsing. (Write the prose with em-dashes; keep the *code* plain.)
- Match the listener via `Get-NetTCPConnection -LocalPort <p> -State Listen`, take `OwningProcess`, then resolve its CommandLine via `Get-CimInstance Win32_Process -Filter 'ProcessId = <pid>'`. `Get-Process` alone won't give you the command line.

## The canonical shape

`app-launcher`'s merged `tray.bat` is the reference implementation. The two load-bearing blocks:

**Idempotent single-instance detection** (CIM, scoped to this repo's `.venv` via **CommandLine** — never `ExecutablePath`, never a bound port — matched on the tray's own command line):

```bat
set "PS=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
set "TRAY_VENV=%SCRIPT_DIR%.venv"
set "TRAY_PIDS="
for /f "usebackq delims=" %%P in (`%PS% -NoProfile -NonInteractive -Command "$v=$env:TRAY_VENV; Get-CimInstance Win32_Process -Filter 'Name = ''pythonw.exe'' OR Name = ''python.exe''' | Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($v, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and $_.CommandLine -match 'launcher\.py\s+tray' } | Select-Object -ExpandProperty ProcessId"`) do (
    if defined TRAY_PIDS (set "TRAY_PIDS=!TRAY_PIDS! %%P") else (set "TRAY_PIDS=%%P")
)
```

**Reclaim-then-start `--restart`** (subtree kill, then the orphan-proof port-reclaim scoped by **CommandLine**, then a short release delay):

```bat
if defined WANT_RESTART (
    if defined TRAY_PIDS (
        for %%P in (!TRAY_PIDS!) do taskkill /T /F /PID %%P >nul 2>&1
    )
    REM Orphan-proof: reclaim this app's service ports from ANY holder whose
    REM CommandLine is under this repo's .venv, even one detached from the tray
    REM subtree above. Match CommandLine (not the image path): a venv-launched
    REM pythonw re-execs the base interpreter, so .Path reports the shared base
    REM python while CommandLine still carries the .venv path.
    set "RECLAIM_VENV=%SCRIPT_DIR%.venv"
    %PS% -NoProfile -NonInteractive -Command "$v=$env:RECLAIM_VENV; foreach ($port in 8445,8446) { Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $opid = $_.OwningProcess; $cim = Get-CimInstance Win32_Process -Filter ('ProcessId = {0}' -f $opid) -ErrorAction SilentlyContinue; if ($cim -and $cim.CommandLine -and $cim.CommandLine.IndexOf($v, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { Write-Host ('Reclaiming :{0} from PID {1}' -f $port, $opid); Stop-Process -Id $opid -Force -ErrorAction SilentlyContinue } } }"
    REM Give Windows a moment to release the ports before rebinding.
    ping 127.0.0.1 -n 3 >nul
)
```

Adapt per repo:

- **Ports** — replace `8445,8446` with the ports *this tray owns*. `photo-ocr` → `8444`. `voice-transcriber` → `8443` (plus `:8091` only if the tray owns it; **not** `:8090`, which is mutex-shared with the local-LLM hub).
- **Tray match** — replace `launcher\.py\s+tray` with this project's tray entry invocation.
- Everything else (the `.venv` paths, the CommandLine-scoped reclaim, the release delay) stays as-is.

## Single source of truth

Don't re-derive the reclaim logic per project. Copy the two blocks above verbatim and change only the ports + tray-match regex. The `--restart` recipe (which port to reclaim, which command relaunches, what signal confirms the new build is live — e.g. `GET /api/version` returning the current `git_sha`) also gets a one-line entry in each repo's own `CLAUDE.md` under `## This repository`.

## Decision log

- **2026-06-07** — Extended the CommandLine correction to the **single-instance detection** block (`project-scaffolding#36`). The 2026-06-04 fix below corrected only the `--restart` port-reclaim half; the detection `Where-Object` kept the `ExecutablePath.StartsWith(<repo>\.venv\Scripts)` guard. On a python.org "pythoncore" venv that guard never matched a live tray (the venv `pythonw.exe` re-execs the base interpreter, so `ExecutablePath` reports `…\pythoncore-3.14-64\pythonw.exe`), so plain `tray.bat` stopped no-op'ing and **stacked a second tray** each run; the duplicate trays then deadlocked the webapp port (each idempotent webapp manager no-ops while a sibling holds the port, so none binds). Observed live on `whatsapp-radar` (`:8455` would not bind until the duplicates were cleaned to one). Detection now matches on `CommandLine.IndexOf($v, OrdinalIgnoreCase) -ge 0` against this repo's `.venv` (same pattern as the reclaim block), still AND-ed with the `launcher\.py\s+tray` invocation match so a sister-app tray is never detected or killed. Carry the same one-line change to each sister `tray.bat` (app-launcher, whatsapp-radar, photo-ocr, voice-transcriber).
- **2026-06-04** — Corrected the canonical scope guard from **process image path** to **CommandLine**. The original `project-scaffolding#29` sketch scoped the reclaim by `$p.Path.StartsWith($venv)` (image path). Proven wrong during the app-launcher rollout (#122): on Python 3.14 Windows venvs a venv-launched `pythonw.exe` re-execs the base interpreter, so the running webapp/session-host reports the shared base interpreter as its image path, not the repo's `.venv`. An image-path guard never matched the real webapp and the reclaim silently no-op'd — the exact failure the convention exists to prevent. The working form (in app-launcher's merged `tray.bat`) matches the holder's `.venv` path against its `CommandLine`. Also recorded the caveat that mutex-shared ports must be excluded from the reclaim list.
