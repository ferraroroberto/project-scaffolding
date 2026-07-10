# Robust Windows tray: idempotent start + orphan-proof restart (didactic)

Personal reference for projects that ship a **Windows tray app owning a long-lived service** (a uvicorn webapp, a PTY session-host, a cloudflared tunnel) launched on login. Captures the *mental model* and the canonical `tray.bat` shape that keeps a restart from silently serving stale code. Sister-app trays (`app-launcher`, `photo-ocr`, `voice-transcriber`) derive from this.

> **Audience.** Me, plus any AI coding agent I hand a project to.
> **Status.** Living reference, not a changelog. Update in place when the recipe changes.
> **Canonical records.** The full tray-lifecycle gotcha series, oldest first: **#12** (single-instance via a named mutex, not a bound TCP port), [**#13**](https://github.com/ferraroroberto/project-scaffolding/issues/13) (`CREATE_NO_WINDOW` when shelling out to console tools), [**#29**](https://github.com/ferraroroberto/project-scaffolding/issues/29) (orphan-proof port reclaim on restart — this doc's original anchor), [**#39**](https://github.com/ferraroroberto/project-scaffolding/issues/39) (the single-instance mutex must hold *in-process* and adopt-or-spawn must be *race-safe*), [**#35**](https://github.com/ferraroroberto/project-scaffolding/issues/35) (non-blocking agent-side restart + child re-adoption), [**#54**](https://github.com/ferraroroberto/project-scaffolding/issues/54) (the full detect → kill → reclaim → start → verify lifecycle must live in one committed `.ps1` call, not inline `-Command` or cmd `for /f` capture, so a non-interactive `--restart` can't silently degrade to adopt-the-stale-build).

---

## TL;DR

- A `start` script is not a `restart` script. Re-running `tray.bat` while an instance is up just spawns a duplicate (or silently no-ops once a port is bound). The pattern is **kill-then-start**, never "run start again".
- A restart must **not** assume the old instance's service-bound children are still in the tray's process subtree. They can orphan. `taskkill /T /PID <tray>` alone misses an orphan, the fresh tray can't bind the port, and the old orphan keeps serving stale code while the restart *reports success*.
- The reliable mechanism is a **port-reclaim sweep**: for each fixed loopback port the app owns, find the current listener and kill its owning PID, scoped to **this app's `.venv`**, *then* start.
- Scope the sweep by the holder's **CommandLine**, not its process image path. On Python 3.14 Windows venvs a venv-launched `pythonw.exe` re-execs the base interpreter, so the process image path reports the *shared base* interpreter — only the CommandLine still carries the `.venv` path. A path-based guard never matches the real webapp and the reclaim silently no-ops.
- Single-instance must be enforced **in the tray process** by a named mutex, not by the launcher `.bat`'s pre-check alone — two near-simultaneous starts both pass the `.bat`'s CIM blind-spot and both survive. Adopt-or-spawn must be **race-safe** (serialize the check-then-spawn), or two trays both spawn a duplicate service. One byte-identical primitive does both: `app/tray/single_instance.py`.
- A restart is **adopt / reclaim / spawn**, not reclaim-only: re-attach to healthy owned children, kill stale port-holders, spawn only what's missing. Classify every child as **owned-and-cycled** (dies + respawns) or **linked-and-preserved** (PTY windows / launched apps that must survive a restart) — the reclaim sweep touches only the former.
- The **agent** invokes `tray.bat --restart` fire-and-forget and verifies with a **bounded** poll of `GET /api/version` (hard timeout + attempt cap, fail loud) — never a foreground launch, never an unbounded wait, never re-deriving the kill by hand.

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
4. **Wait briefly** for Windows to release the ports, then start.
5. **Verify the served build** by polling `GET /api/version` and comparing its `git_sha` to repo `HEAD`. A stale mismatch is a hard non-zero failure.

### Scope by CommandLine, not image path (the correction that matters)

The obvious scope guard — "only match the process if its *image path* is under `<app>\.venv`" — is **wrong on modern Windows venvs** and was corrected out of the canonical form. On Python 3.14, a venv-launched `pythonw.exe` re-execs the *base* interpreter, so a running tray/webapp/session-host reports the **shared base interpreter** as its image path (`Get-Process.Path` / `Win32_Process.ExecutablePath` = `…\pythoncore-3.14-64\pythonw.exe`), not the repo's `.venv`. Only the process **CommandLine** still carries the `.venv` path (it's how the venv launcher invoked it). An image-path guard therefore *never matches the real process*, the operation silently no-ops, and you get back the exact "reports success, changes nothing" failure the convention exists to prevent.

This applies to **both** uses of the per-app match: the `--restart` **port-reclaim** (which holder to kill) **and** the single-instance **detection** (is a tray already running?). The original 2026-06-04 correction fixed only the reclaim block; the detection block kept an `ExecutablePath.StartsWith(...)` guard and so never recognised a live tray on a pythoncore venv — every `tray.bat` invocation then stacked another tray and the webapp port deadlocked. Both blocks now match on CommandLine.

Match on `CommandLine` containing the repo's `.venv` path (ordinal, case-insensitive). That uniquely identifies *this* app's processes while leaving sibling apps' processes (and unrelated processes that merely happen to hold the port) untouched.

### Only reclaim ports the tray definitively owns

A port that is **mutex-shared with another app** must **not** go in the reclaim list. Example: an audio/whisper port (`:8090`) shared between a voice-transcriber tray and the local-LLM hub. Reclaiming a shared port would kill the *other* app's legitimately-running process. List only the ports this tray exclusively owns (its own webapp / session-host). Shared ports are coordinated by mutex, not reclaimed.

## Platform gotcha (Windows / PowerShell 5.1)

- `tray.bat` shells out to **Windows PowerShell 5.1** (`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`), running the whole lifecycle via one `-File app\tray\tray_lifecycle.ps1 launch ...` call. Keep that `.ps1` **ASCII-only** — a stray em-dash or other non-ASCII char breaks PS 5.1 parsing. (Write the prose with em-dashes; keep the *code* plain.)
- Match the listener via `Get-NetTCPConnection -LocalPort <p> -State Listen`, take `OwningProcess`, then resolve its CommandLine via `Get-CimInstance Win32_Process -Filter 'ProcessId = <pid>'`. `Get-Process` alone won't give you the command line.

## The canonical shape

`tray.bat.template` is the reference implementation. The load-bearing shape is a single helper invocation:

```bat
set "PS=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
set "TRAY_VENV=%SCRIPT_DIR%.venv"
set "TRAY_PS=%SCRIPT_DIR%app\tray\tray_lifecycle.ps1"
set "OWNED_PORTS=8445,8446"
set "VERSION_URL="
set "RESTART_ARG="
if defined WANT_RESTART set "RESTART_ARG=-Restart"

%PS% -NoProfile -NonInteractive -File "%TRAY_PS%" launch -AppName "%APP_NAME%" -ScriptDir "%SCRIPT_DIR%" -VenvDir "%TRAY_VENV%" -TrayMatch "launcher\.py\s+tray" -Ports "%OWNED_PORTS%" -TrayLaunch "%TRAY_LAUNCH%" -VersionUrl "%VERSION_URL%" !RESTART_ARG!
exit /b %ERRORLEVEL%
```

Inside the helper, `launch` performs idempotent start when `-Restart` is absent; when `-Restart` is present it detects matching tray PIDs, kills the tray subtree, reclaims owned ports by CommandLine-scoped PID, starts the tray, and polls the version endpoint until served `git_sha` matches repo `HEAD`.

### The lifecycle lives in a committed `.ps1`, not cmd capture (the non-interactive fix)

The batch shells to `%PS% … -File "%SCRIPT_DIR%app\tray\tray_lifecycle.ps1" launch ...` once rather than embedding the CIM/`Get-NetTCPConnection` logic in inline `powershell.exe -Command "…"` or parsing helper output through `for /f`. This is load-bearing, not cosmetic. The first broken shape needed a CIM `-Filter` with **doubled single quotes nested inside the batch's double quotes**, all inside a `for /f usebackq` **backtick** block. The second broken shape moved the CIM logic to `-File` but still wrapped `detect` in `for /f`; launched **non-interactively through a nested shell** — Git Bash → `cmd /c "tray.bat --restart"`, or a finisher skill's Bash tool — that capture can still return **empty**. Neither the running tray nor the port holder is found, so `--restart` silently degrades to a plain start.

That degradation is dangerous precisely because **a plain start adopts whatever is already serving the port**: a tray's `WebappManager.start()` runs `status()` first and, finding a live listener, *adopts* it (`OWNERSHIP_EXTERNAL`) and returns healthy — it never swaps in new code. The **only** thing that forces a new build to load is `--restart`'s reclaim killing the old holder *before* the fresh tray starts. So a mangled detection doesn't just "miss a kill" — it turns `--restart` into "adopt the stale build" while reporting success. Observed live (project-scaffolding#54, `whatsapp-radar`): the run emitted only the `cmd` banner, none of the batch's own `Stopping previous…` echoes, the old trays survived, and `GET /api/version` kept reporting the previous `git_sha`.

Shelling once to the helper removes cmd output parsing from the lifecycle entirely (app-specific values — venv path, tray-match regex, owned ports, tray launch, optional version URL — are passed as plain arguments), so detection, reclaim, start, and verification behave **identically** whether `tray.bat` is run from an interactive console, the Startup folder, or a non-interactive agent shell. `tray_lifecycle.ps1` is **vendored verbatim** alongside `single_instance.py` (only its arguments differ per app), and `tray.bat` hard-errors if the helper is missing rather than silently no-op'ing back into the stale-adopt failure.

**Verification is by served `git_sha` vs repo `HEAD`, never a `healthz` 200** — a stale adopted process passes a health check fine. The agent owns the bounded version-endpoint poll (see "The agent-side contract" below); `fleet-config`'s `/issue-finish` invokes `tray.bat --restart` through a real Windows shell and **stops + surfaces** a `git_sha ≠ HEAD` mismatch rather than improvising process kills (`fleet-config#89`).

Adapt per repo:

- **Ports** — replace `8445,8446` with the ports *this tray owns*. `photo-ocr` → `8444`. `voice-transcriber` → `8443` (plus `:8091` only if the tray owns it; **not** `:8090`, which is mutex-shared with the local-LLM hub).
- **Tray match** — replace `launcher\.py\s+tray` with this project's tray entry invocation.
- Everything else (the `.venv` paths, the CommandLine-scoped reclaim, the release delay) stays as-is.

## Single source of truth

Don't re-derive the lifecycle logic per project. A copy-to-adapt **`tray.bat.template`** ships at the scaffold root — for a new tray app, copy it to `tray.bat` and replace the four `__PLACEHOLDER__` tokens (`__APP_NAME__`, `__TRAY_LAUNCH__`, `__TRAY_MATCH__`, `__OWNED_PORTS__`); a filled-in copy is byte-identical to every sister tray. For an existing tray, replace the cmd-side detect/reclaim/start blocks with the single `launch` helper call and change only the ports + tray-match regex. The `--restart` recipe (which port to reclaim, which command relaunches, what signal confirms the new build is live — e.g. `GET /api/version` returning the current `git_sha`) also gets a one-line entry in each repo's own `CLAUDE.md` under `## This repository`.

The lifecycle helper **`app/tray/tray_lifecycle.ps1`** is **vendored verbatim** the same way as the mutex primitive — copy it byte-for-byte alongside `tray.bat`, never edit it per-app (the venv path, tray-match regex, owned ports, tray launch, and optional version URL are passed as arguments by `tray.bat`, so the file stays identical fleet-wide). It exists so detect → kill → reclaim → start → verify is never embedded in cmd parsing whose quoting/capture breaks under a non-interactive call (see the non-interactive-fix section above). A new tray app therefore vendors **two** scaffold files — `tray_lifecycle.ps1` and `single_instance.py` — plus the filled-in `tray.bat`.

The in-process single-instance + race-safe adopt-or-spawn primitive (gotcha #4) ships the same way: **`app/tray/single_instance.py`** is **vendored verbatim** — copy it byte-for-byte into each tray app, never edit it per-app (the app-specific mutex *names* are passed at the call site, so the file stays identical fleet-wide). A fix made once in the scaffold re-propagates by re-copying.

## Gotcha #4 — single-instance must hold in-process; adopt-or-spawn must be race-safe

`project-scaffolding#39`. The #29 machinery cleans up the *previous* instance on restart; this is the orthogonal guarantee that a *single start* never creates *two*. Two independent layers, both proven on `whatsapp-radar` from a verified-clean baseline (one `tray.bat` spawned two trays + two uvicorns contending for one port):

1. **The single-instance lock must live in the tray process.** `tray.bat`'s pre-launch CIM detection is necessary but not sufficient: two near-simultaneous launches both read the process table before either tray is visible, both pass the check, and both survive. Per #12 the guarantee belongs to a **named mutex held by the tray process itself** — acquire it at the top of `run_tray()`; if another process already holds it, exit immediately. The `.bat` check stays (it makes the common case a fast no-op), but it is the *outer* guard, not the only one.
2. **Adopt-or-spawn must be race-safe.** A `WebappManager.start()` that does `status()` (is the port in use?) then `Popen(uvicorn)` is check-then-act: two trays that both observe "not running" before either binds will **both** spawn — a TOCTOU race. Serialize the critical section with a named mutex keyed on the owned port so the second caller blocks, then sees the now-listening port and **adopts** instead of spawning.

Both are solved by one byte-identical primitive vendored verbatim from the scaffold — `app/tray/single_instance.py`:

```python
# tray entry -- in-process single instance (held for the process lifetime)
from app.tray.single_instance import SingleInstance, cross_process_lock

_instance = SingleInstance(r"Global\whatsapp-radar-tray")
if not _instance.acquired:
    logger.info("Another whatsapp-radar tray is already running; exiting.")
    return 0

# WebappManager.start() -- race-safe adopt-or-spawn
with cross_process_lock(rf"Global\whatsapp-radar-webapp-start-{self.config.port}"):
    current = self.status()
    if current.running:          # someone bound it while we waited -> adopt
        return current
    self._proc = subprocess.Popen(self._build_command(), ...)
```

The mutex *names* are the only per-app difference; the file is identical everywhere. A `Global\` prefix makes the lock span terminal-server sessions; use a bare/`Local\` name only if per-session scope is what you want.

**The cascade caveat.** On a python.org "pythoncore" venv the symptom can *look* like a double-spawn even after the locks are correct: a venv-launched `pythonw.exe` re-execs the base interpreter, so each logical process appears as a parent/child PID pair (the venv stub waiting on the re-exec'd child). That is two PIDs, one logical process — distinct from the genuine double-spawn the locks fix. Pin which one you're seeing (parentage + CommandLine) before concluding the lock failed.

## Re-adoption and child lifecycle on restart

`project-scaffolding#35`. The #29 sweep only ever **reclaims** (kills stale port-holders). A correct restart is the fuller **adopt / reclaim / spawn**:

- **Adopt** the owned children already up *and healthy* (re-attach, don't kill-and-respawn) — and reload cache/assets as part of normal boot.
- **Reclaim** the stale ones (a port-holder under this `.venv` that is unhealthy or that the fresh tray supersedes).
- **Spawn** only what is actually missing.

"Don't spawn it 20 times" is exactly this: discover-then-decide, never blind-spawn.

**Child-lifecycle classes — classify every tray child as one of:**

| Class | Examples | On tray restart |
|---|---|---|
| **owned-and-cycled** | the uvicorn webapp, a worker, cloudflared | dies + respawns to pick up new code (or is adopted if already healthy); its port **is** in the reclaim list and it lives **inside** the tray's process subtree, so the `/T` subtree kill cleans it up |
| **linked-but-independent** | `app-launcher`'s session-host + its PTY-backed shells, externally-launched apps | must **survive** the restart and re-attach; **spawned re-parented out of the tray subtree** (via `cmd /c start`, *not* a creation flag) so `taskkill /T` can't reach them; never in the reclaim sweep |

**The detach + re-adopt mechanism is what makes a `/T` restart safe — "must survive" is enforced by *where the child runs*, not by hope.** A linked child spawned as an ordinary tray subprocess is in the tray's subtree, so `tray.bat --restart`'s `taskkill /T /F /PID <tray>` cascades into it and kills it. This is the documented footgun: a `--restart` run from inside an `app-launcher`-hosted Coding session killed the user's own PTY, because the session-host on `:8446` was a child of the tray supervisor (`app-launcher` issue #81 / `feedback_tray_restart_kills_sessions`). The fix is structural, not a warning label: **spawn linked-but-independent children re-parented out of the tray subtree** so they are not in the kill tree, and have the **fresh tray re-adopt them on start** by port/identity. **Re-parenting is the load-bearing detail — and `CREATE_NEW_PROCESS_GROUP` / `DETACHED_PROCESS` do NOT achieve it** (empirically verified: `taskkill /T` walks the parent-child *PID tree*, which those creation flags don't change, so the child is still killed). The reliable way on Windows is to launch through an intermediary that exits, orphaning the child out of the tray's tree — e.g. `cmd /c start "" /b <pythonw> launcher.py session-host` (cmd exits, the session-host's parent is gone, `/T` can't reach it). The adopt side is the same race-safe adopt-or-spawn as the webapp (adopt if healthy, reclaim only if stale). Then one `tray.bat --restart` is deterministic *and* safe: it `/T`-kills the tray + the owned-and-cycled subtree (webapp, cloudflared), reclaims owned ports (orphan-proof, #29), and starts a fresh tray that **adopts the surviving detached children and respawns the cycled ones with new code** — safe to run even from inside a session the tray's session-host is hosting, because that session-host is no longer in the kill tree.

`app-launcher` is the motivating case and the only fleet tray with linked children: its session-host (`:8446`) must live *outside* the tray subtree (detached) and be adopted on start. Every other fleet tray has only owned-and-cycled children, so a `/T` restart is already safe for them today. The reclaim list holds *only* owned-and-cycled ports; mutex-shared and linked-preserved ports stay out of it. Until a tray with linked children is detach-compliant, its `CLAUDE.md` `## This repository` must say so — and `tray.bat --restart` stays a confirm-first operation there.

## The agent-side contract: invoke + bounded-verify, never re-derive

`project-scaffolding#35`, gap 1 — where the 10–20-minute hangs actually lived. The intelligence (which ports, which children, what to reclaim) belongs in the app's `--restart`, which already holds it; the agent must **delegate**, not reconstruct:

1. **Invoke `tray.bat --restart` fire-and-forget** — the *single* canonical restart, the same command for every tray (no per-app branching). A tray launcher is long-lived and holds the console it starts in; run as a normal foreground tool call it never returns and burns the tool timeout. The `.bat`'s relaunch is already detached (`start "Title" pythonw …` returns immediately), so the *agent* must also call it non-blocking (background/detached) so the tool returns at once. **Safety precondition:** this is safe for any tray whose linked-but-independent children are detached + adopted (per the section above) — true for every tray with only owned-and-cycled children. For a tray that still hosts linked children *in its subtree* (until it is made detach-compliant), `--restart` will kill them; its `CLAUDE.md` flags this and the agent must confirm first.
2. **Verify with a bounded poll of the build signal.** Poll `GET /api/version` (live `git_sha` + asset hash) with a **hard timeout and attempt cap** (e.g. ≤30 s / fixed attempts), then **fail loud**. A slow or failed boot must become a fast, explicit failure — never an open-ended wait.
3. **Assert `git_sha == HEAD`** and report the build line. A health check alone is not enough — a stale process answers `/healthz` fine.

No `Get-NetTCPConnection`/PID-hunting in the agent skill: that logic lives in `--restart`. A hand-rolled kill only catches the one listener it finds and misses the orphan the reclaim sweep exists to kill. The same recipe is mandated agent-side in the scaffold `CLAUDE.md` ("Restart and verify before hand-off") and in the `/issue-finish` finisher.

## Decision log

- **2026-07-10** — Fixed the canonical template's own `launch` call (`project-scaffolding#145`), found the first time the post-#54 template was exercised **live** rather than statically (`photo-ocr#98`). `%~dp0` ends in a trailing backslash, and Windows argv parsing treats an odd run of backslashes before a closing quote as escaping it — so `-ScriptDir "%SCRIPT_DIR%"` swallowed the rest of the command line and `-TrayMatch` / `-Ports` reached the helper **empty**. Detect matched nothing, reclaim reclaimed nothing, and `--restart` degraded to exactly the adopt-the-stale-build start #54 exists to prevent: the fix reintroduced the bug it fixed. `SCRIPT_DIR` keeps its trailing separator for the path joins; a de-slashed `SCRIPT_DIR_ARG` is passed as the argument. Guarded by `tests/test_tray_lifecycle.py::test_tray_template_launch_args_survive_argv_parsing`, which drives the real template through a real `cmd` + `powershell -File` and reads the parsed switches back — the text-grep template tests could not see this, and did not.
- **2026-07-08** — Documented the **`CREATE_NO_WINDOW`** convention (`project-scaffolding#13`), the fleet's second tray-lifecycle gotcha, after `local-llm-hub`'s Hub-tab health poll flashed a console window every 5–10s shelling to `docker info`/`nvidia-smi` without the flag. Out of scope here since the console-subprocess pattern applies to any Windows tray/daemon/GUI app generally, not the restart lifecycle this doc covers (same split as the note directly below) — the convention + worked helper live in `docs/app-onboarding.md` §1 and the `CLAUDE.md` "Windows console-subprocess suppression (`CREATE_NO_WINDOW`)" section instead.
- **2026-07-08** — Filed the **event-loop pinning** convention (`project-scaffolding#130`) after a fleet-wide investigation (`app-launcher#388`) found the Windows proactor-loop accept-socket wedge in every sister webapp. Out of scope here since `app/webapp/manager.py`/`server.py` live in sister projects, not the scaffold (same split as the note directly below) — the convention + reference shim live in `docs/app-onboarding.md` §1 and the `CLAUDE.md` "Windows event-loop pinning (uvicorn)" section instead.
- **2026-06-22** — Completed the `project-scaffolding#54` fix after the first `-File` move proved incomplete. The reopened repro (`home-automation#77`) showed the helper worked standalone, but `tray.bat` still wrapped `detect` in cmd `for /f usebackq`; from Git Bash → `cmd /c "tray.bat --restart"`, that capture returned empty, so the tray kill and port reclaim no-op'd, the stale webapp was adopted, and the batch exited 0. The canonical template now delegates the full **detect → kill → reclaim → start → verify** sequence to one `tray_lifecycle.ps1 launch ...` call, with no cmd-side helper-output parsing. On `--restart`, the helper polls `/api/version`, compares served `git_sha` to repo `HEAD`, and exits non-zero on a stale serve. Sister trays re-vendor `tray_lifecycle.ps1` + the updated `tray.bat` helper call. *Still out of scaffold scope: the `WebappManager.restart()` "restart an external owner" / adopt-external precedence change lives in sister projects' `app/webapp/manager.py`, which the scaffold does not carry.*
- **2026-06-09** — Moved the tray's CIM **detection** and port **reclaim** out of inline `powershell.exe -Command "…"` blocks in `tray.bat` and into a committed, vendored-verbatim **`app/tray/tray_lifecycle.ps1`** shelled to with `-File` (`project-scaffolding#54`). This fixed the inline `-Command` nested-quote failure, but not the later cmd `for /f` capture around the helper; the completed 2026-06-22 entry above supersedes this partial fix.
- **2026-06-07** — Reconciled the **agent-safe restart** model (`project-scaffolding#35`) after finding the canonical `tray.bat --restart` mandate (#41/#43) collided with the user's recorded feedback that it destroys live PTY sessions. Resolution keeps `tray.bat --restart` as the *single* canonical command (no revert of #41/#43) and fixes the root cause structurally: **linked-but-independent children are spawned re-parented out of the tray subtree (via `cmd /c start`; `DETACHED_PROCESS` does *not* escape `/T`, verified by probe) and re-adopted on start**, so a `/T` restart cleans only the owned-and-cycled subtree and can never reach the session-host / PTY — safe to run even from inside a hosted session. Builds on #29 (reclaim) + #39/#44 (adopt-or-spawn as the adoption engine); retires the fragile "kill only :8445 + bare `tray.bat`" workaround. The one code change lands in `app-launcher` (detach + adopt its `:8446` session-host); every other tray has only owned-and-cycled children and is already `/T`-safe.
- **2026-06-07** — Added the **in-process single-instance + race-safe adopt-or-spawn** convention (gotcha #4, `project-scaffolding#39`) and the **agent-safe restart + re-adoption** convention (`#35`). Shipped the byte-identical `app/tray/single_instance.py` primitive (`SingleInstance` for the tray's in-process lock; `cross_process_lock` to serialize the webapp adopt-or-spawn) so neither #39 layer is re-derived per app. Documented the **adopt / reclaim / spawn** restart model and the **owned-and-cycled vs linked-and-preserved** child-lifecycle classification (app-launcher's PTY/linked apps as the worked example), plus the **agent-side contract** (invoke `--restart` fire-and-forget, bounded version-endpoint poll, fail loud — no hand-rolled PID hunting). The #39 root cause was proven on `whatsapp-radar` (one clean `tray.bat` spawned two trays + two uvicorns); the fix re-propagates to each sister tray via pointer issues.
- **2026-06-07** — Shipped the canonical **`tray.bat.template`** at the scaffold root and mandated the **`tray.bat --restart`** invocation across the toolchain (`project-scaffolding#40`, `fleet-config#78`, fleet pointer issues). Closed the enforcement gap where the `/issue-finish` and `/issue-yolo` skills told the agent to hand-roll a `Get-NetTCPConnection`/`taskkill` restart instead of calling the deterministic `tray.bat --restart` — a hand-rolled kill only catches the one listener it finds and misses the orphan the reclaim sweep exists to kill. The skills now name `tray.bat --restart` as the primary path (manual kill = fallback only); the scaffold `CLAUDE.md` mandates the invocation; and `local-llm-hub` — the lone fleet tray still on the old start-only shape — was brought up to the canonical form (reclaims `:8000`, excludes the mutex-shared `:8090`). Each tray app's `CLAUDE.md` `## This repository` section now names `tray.bat --restart`.
- **2026-06-07** — Extended the CommandLine correction to the **single-instance detection** block (`project-scaffolding#36`). The 2026-06-04 fix below corrected only the `--restart` port-reclaim half; the detection `Where-Object` kept the `ExecutablePath.StartsWith(<repo>\.venv\Scripts)` guard. On a python.org "pythoncore" venv that guard never matched a live tray (the venv `pythonw.exe` re-execs the base interpreter, so `ExecutablePath` reports `…\pythoncore-3.14-64\pythonw.exe`), so plain `tray.bat` stopped no-op'ing and **stacked a second tray** each run; the duplicate trays then deadlocked the webapp port (each idempotent webapp manager no-ops while a sibling holds the port, so none binds). Observed live on `whatsapp-radar` (`:8455` would not bind until the duplicates were cleaned to one). Detection now matches on `CommandLine.IndexOf($v, OrdinalIgnoreCase) -ge 0` against this repo's `.venv` (same pattern as the reclaim block), still AND-ed with the `launcher\.py\s+tray` invocation match so a sister-app tray is never detected or killed. Carry the same one-line change to each sister `tray.bat` (app-launcher, whatsapp-radar, photo-ocr, voice-transcriber).
- **2026-06-04** — Corrected the canonical scope guard from **process image path** to **CommandLine**. The original `project-scaffolding#29` sketch scoped the reclaim by `$p.Path.StartsWith($venv)` (image path). Proven wrong during the app-launcher rollout (#122): on Python 3.14 Windows venvs a venv-launched `pythonw.exe` re-execs the base interpreter, so the running webapp/session-host reports the shared base interpreter as its image path, not the repo's `.venv`. An image-path guard never matched the real webapp and the reclaim silently no-op'd — the exact failure the convention exists to prevent. The working form (in app-launcher's merged `tray.bat`) matches the holder's `.venv` path against its `CommandLine`. Also recorded the caveat that mutex-shared ports must be excluded from the reclaim list.
