# Request budget ratchet

`scripts/request_budget_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It reads browser JavaScript and server Python, counts each rule's hits per file, and **fails when a file's count for a rule rises** above the committed baseline. Existing debt never blocks work; it cannot grow either.

It holds the decision that polling web apps keep a request budget ([architecture decisions](architecture-decisions.md), "Polling web apps keep a request budget"). The rules and the reasons behind them are in [polling-budget.md](polling-budget.md); this page is the mechanism: what each rule reads, its scope, exit codes, baseline and modes.

It has the shape of the [usage track ratchet](usage-track-ratchet.md): an opt-in `.fleet.toml` table, named rules, a committed baseline, the same flags, and exit 3 for "not confirmed". It is stdlib-only and loads one sibling, `scripts/request_budget_scan.py`, which holds the readers. Every rule is decided from source alone, so the same tree gives the same answer on every run and every machine.

## The rules

Every rule is on unless `rules` narrows the list. The `RB` numbers are the ones [polling-budget.md](polling-budget.md) uses.

### `fixed-rate-poll`

RB1. A `setInterval(...)` call (also `window.`, `globalThis.` or `self.setInterval`), or a call to a name listed in `poll_wrappers` (a repo's own wrapper around `setInterval`, such as a `createPoller`), whose callback reaches a server call. The callback is read from the call's first argument:

- an inline function or arrow: its own text;
- a name: the function of that name the same file defines (`function f`, or `const f = ... =>` / `function`);
- anything else (`this.refresh`, `tick.bind(this)`): it cannot be read, so it counts.

It reaches a server call when its text has `fetch(`, `XMLHttpRequest`, `EventSource(`, `sendBeacon(`, `axios`, `$.ajax/get/post/getJSON(` or a name listed in `fetch_wrappers`, or calls (by bare name) a function the file defines that does, followed to any depth. A bare call to a name the file does not define (an import, an injected reader) cannot be ruled out, so it counts too. Built-in globals (`String`, `parseInt`, `setTimeout`, ...) and `new X(...)` are not calls it follows. A pure on-screen clock whose callback the file can read passes with no marker; one that calls something it cannot read carries `request-budget-exempt: <reason>`.

### `poll-floor`

RB2. A poll interval under **2000 ms**, judged on two kinds of call:

- a `startPoll(read, ms, opts?)` call (the vendored helper), unless its third argument declares `activeWhile:` (it runs only while a job is in progress);
- a `fixed-rate-poll` hit's interval (it then counts for both rules).

The interval counts when it is a numeric literal (`1500`, `1_500`), a product of literals (`2 * 500`), or a name bound to one by `const` in the same file. An interval the source does not fix (`settings.pollMs`) is not judged: the rule is about literals, and that interval belongs in the app's Settings anyway.

### `unwatched-loop`

RB3. A server loop that runs whether or not anyone is looking:

- a `while` loop whose test or body (not counting nested functions) calls `sleep(...)` (`time.sleep`, `asyncio.sleep`, an injected `sleep`) or `wait(timeout)` (`stop.wait(1)`);
- a `threading.Timer(delay, f)` or `loop.call_later(delay, f)` whose callback is the function it is created in (a timer that re-arms itself). A one-shot timer is not a loop.

It is a hit when the loop sleeps under **5 s**, sleeps for an interval the source does not fix (a literal, arithmetic over literals, or a module-level constant bound to one), or starts an outside program on each pass (`subprocess.*`, `asyncio.create_subprocess_*`, `os.system`, `os.popen`, `os.startfile`), whatever its interval. A loop declared in `.fleet.toml` passes:

```toml
[[request_budget.loops]]
path       = "src/watcher.py"
function   = "Watcher.run"   # the enclosing function, dotted through classes; "<module>" at top level
interval_s = 1
why        = "reads the hardware's state while nobody is viewing"
```

Every key is required. A declaration that no loop matches any more is printed on every run so it can be removed.

### `scan-per-request`

RB4. A directory scan inside a request-handler module: a call named `walk` on `os`, `glob`/`iglob` on `glob`, any `.glob(`, `.rglob(`, `.iterdir(`, `.scandir(` or `.listdir(`, or a bare `scandir`/`listdir`/`iglob`/`walk` import. Handler modules are the Python files under `handler_dirs`; with none declared the rule is **OFF** and every run says so. A module that imports a module listed in `stat_cache` passes: its reads go through the shared `(path, size, mtime_ns)` cache.

### `default-pool`

RB5. `asyncio.to_thread(...)` (or a bare `to_thread(...)`) and `run_in_executor(None, ...)`: work submitted to the event loop's one shared default pool. New work goes to a named pool for its class (`TimedExecutor("hot-poll", 4)` from the vendored [request-timing middleware](polling-budget.md#the-request-timing-middleware)); large existing counts burn down over time.

### `timing-middleware`

RB6. A repo with a web app (a `FastAPI(` or `Starlette(` call in a file under `server_paths`) where no tracked Python file outside tests and vendored copies imports `RequestTimingMiddleware` (`from ... import RequestTimingMiddleware`, or `request_timing.RequestTimingMiddleware`). One hit, on the line of the first app constructor. A repo with no web app never has this hit.

### `bare-exempt`

A `request-budget-exempt` marker with no reason after a colon. It exempts nothing, and it is a hit wherever it stands.

### Exempting one hit

Write `request-budget-exempt: <reason>` in a comment (`//`, `/* */` or `<!-- -->` in browser code, `#` in Python) on the hit's line or in the run of comment lines right above it; a code line ends the run. The exemption covers every rule's hit on that line. Every run prints the count of exemptions in force and each one with its file, line, rule and reason, so they stay visible in review.

## What is not checked

- **Method calls.** `this.refresh()` or `api.get()` inside a callback is not followed; only bare-name calls and the server-call tokens are. A fetch behind a method in another object is missed. A callback that is itself a method reference counts, conservatively.
- **Other files.** A function imported from another module is not opened; calling it counts (it cannot be ruled out), which is the safe direction.
- **Template-literal expressions.** Code inside `${...}` is blanked with the template, so a `fetch` there is not seen.
- **Self-scheduling `setTimeout` polls.** They do not overlap, so RB1 does not count them; the browser probe ([polling-budget.md](polling-budget.md#the-runtime-check)) catches one that keeps polling while hidden.
- **Run-time behaviour.** The ratchet reads source. How many requests a page really makes in a minute, visible and hidden, is the job of the [runtime check](polling-budget.md#the-runtime-check).

## Scope

- **Browser code:** every tracked or untracked-but-not-ignored file under `browser_paths` (default `app/webapp/static/**`, `app/webapp/templates/**`) with a JS suffix (`.js`, `.mjs`, `.cjs`) or an HTML one (`.html`, `.htm`, `.jinja`, `.jinja2`, `.j2`). In HTML only inline `<script>` blocks are read; a `<script src>` loads a file scanned on its own, and a JSON script block is data.
- **Server code:** every such `.py` file under `server_paths` (default `src/**`, `app/**`).
- **Never scanned:** test folders (`tests/`, `test/`), `node_modules`, `.venv`, `*.min.js`, the globs in `exclude`, and every `[vendored]` destination: a vendored copy's debt belongs to the repo it came from. The middleware import (RB6) is looked for in every tracked Python file outside tests and vendored copies, not only under `server_paths`.
- A baseline file, this stage's or any other ratchet's, is JSON and never read.

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (no rule count above the baseline), or the stage is **not enabled** | continues |
| `1` | A file's count for a rule rose, or the baseline file is missing | fails |
| `2` | Bad `[request_budget_ratchet]` or `[request_budget]` table (unknown key or rule, a malformed loop declaration, a wrapper that is not a JS name), unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: `git` unusable, a file that cannot be read or is not UTF-8, JS whose string, comment or regex literal never closes or whose call brackets never close, or Python that does not parse. The message names the file and line | fails |

Exit 3 is its own state and never folded into a pass: a file the stage cannot read through has an unknown count, not zero.

## The baseline file

`.ratchets/request-budget.json` at the repo root (or `baseline`), one entry per file with hits, its counts per rule, no line numbers:

```json
{
  "version": 1,
  "entries": [
    {"key": "app/webapp/static/main.js", "counts": {"fixed-rate-poll": 3, "poll-floor": 1}},
    {"key": "app/webapp/server.py", "counts": {"timing-middleware": 1}}
  ]
}
```

A file absent from the baseline holds zero hits. A repo with no web code records `"entries": []`.

## Modes

| Mode | Effect |
|---|---|
| (none) | The gate's check: every file's counts against the baseline, then the exemptions in force, the OFF checks and any stale loop declaration |
| `--init` | Write the first baseline from today's tree; never overwrites an existing one |
| `--update-baseline` | Drop hits that are gone (shrink only); refuses, writing nothing, when a count rose |
| `--update-baseline --allow-additions` | Also record new hits; the added lines show in review |

`--root <dir>` points it at another repo. Raising a baseline is a reviewed decision, never a way to get green.

## Adopting it (opt-in per repo)

1. Copy `scripts/request_budget_ratchet.py` and `scripts/request_budget_scan.py` verbatim and declare both under `[vendored]` (`/propagate-vendored` carries the sibling through `requires`), or run `scripts/tools/adopt_ratchets.py <target> --ratchets request_budget`.
2. Add the table; the defaults suit the fleet's web-app layout:

   ```toml
   [request_budget_ratchet]
   enabled      = true
   handler_dirs = ["app/webapp/routers"]   # where request handlers live; omit and RB4 is OFF
   ```

   Declare `poll_wrappers`, `fetch_wrappers`, `stat_cache` and `[[request_budget.loops]]` as the repo has them.
3. Run `python scripts/request_budget_ratchet.py --init`, review the baseline, commit it with the table.
4. Add the stage to the gate after the UX surface ratchet (`run_ratchets.py` already orders it there).

## Cost

One `git ls-files` per run, then one pass over the in-scope files: on this scaffold (90 browser and server files) a run takes about 0.18 CPU seconds and starts one process. It reads source only and never imports what it scans.

## Tests

`tests/ratchets/test_request_budget_ratchet.py`: a planted hit and the clean form for each rule, the exemption and bare-marker behaviour, every declaration a rule honours, each mode and exit code on throwaway git repos, the "not confirmed" exit, the standalone run with its sibling, and this repo's own table, catalogue entry and gate stage.
