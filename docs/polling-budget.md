# Polling budget

Every fleet web app that polls its own API keeps a request budget, so it stays responsive on a slower computer with several sessions open. This page is the reference: the six rules and why each exists, the two vendored components that make them cheap to follow, the browser check that proves a page keeps them, and where every limit lives. The decision is in [architecture-decisions.md](architecture-decisions.md), "Polling web apps keep a request budget"; the gate stage that holds the code to it is the [request budget ratchet](request-budget-ratchet.md).

## Why

On a slower computer one fleet app reached 10–37 s per request with 17 or more in flight. Nothing was broken: the same app answered in tens of milliseconds on the development machine. The causes were general, not specific to that app:

- browser polls on overlapping `setInterval`s that started a new read whether or not the last one had come back, and kept ticking on a hidden tab or a locked phone;
- a directory walk on every request to find which file belonged to which session;
- a full re-parse of files that had not changed since the last tick;
- one shared thread pool, so a slow fan-out (git status across many repos) made the hot polls queue behind it.

A faster computer hides this waste; it does not remove it. Each rule below removes one shape of it, and each is mechanical enough to check from source or from one browser test.

## The rules

| Rule | Ratchet rule | Says |
|---|---|---|
| RB1 | `fixed-rate-poll` | Browser polls are self-scheduling and single-flight: the next read is scheduled when the last one settles, and each read shape has at most one request in flight per page. Polls go through the vendored `poll` helper, never a `setInterval` that reaches the server. |
| RB2 | `poll-floor` | No poll runs faster than every 2 s, except one that runs only while a job is in progress and says so (`activeWhile`). |
| RB3 | `unwatched-loop` | A server loop that wakes more often than every 5 s, or starts an outside program on each pass, is declared with its interval and why it cannot wait for a viewer. |
| RB4 | `scan-per-request` | A request handler never walks a directory; it reads through the shared stat cache, so unchanged data costs a `stat`. |
| RB5 | `default-pool` | Work runs in bounded pools by class (hot polls, heavy reads, user actions, fan-out scans); nothing new goes to the shared default pool. |
| RB6 | `timing-middleware` | Every web app reports where each request's time went (`queue_ms`, `worker_ms`, `total_ms`) through the vendored request-timing middleware. |

Hidden tabs do not poll: RB1's helper arms no tick while the page is hidden and reads once on the return. The browser check below proves it at run time, where source reading cannot.

**Why each threshold.** 2 s is the slowest a status view can refresh and still feel live; anything faster is a progress bar, which runs only while its job does. 5 s is the point below which a background loop costs measurable CPU on an idle slow machine for data nobody is reading. Both are floors for the ratchet; the interval an app actually uses is a setting (below).

**Exceptions.** One hit that must stay carries `request-budget-exempt: <reason>` in a comment on its line or right above it. The ratchet counts and prints every exemption, so they stay in review.

## The `poll` helper

`app/webapp/static/_vendored/poll/poll.js` (manifest key `poll`), normalized from app-launcher-lite's poll module:

- `startPoll(read, ms, opts?)` calls `read()` `ms` after the last call settled, arms nothing while `document.hidden`, reads once straight away on the return to the foreground, and returns `{ stop, kick }`. `opts.activeWhile` makes it a busy-only poll: while the predicate is false no tick is armed, and `kick()` starts it again.
- `singleFlight(read)` lets every caller that asks while a read is out share it (a poll tick, a tab tap, a retry); `.fresh()` waits for a read that may predate a write and shares the next.

Contract and vendoring steps: the component's [README](../app/webapp/static/_vendored/poll/README.md).

## The request-timing middleware

`src/request_timing.py` (manifest key `request_timing`), lifted from app-launcher-lite's instrumentation. Stdlib only, pure ASGI (it buffers nothing), Python 3.9+:

- `RequestTimingMiddleware` adds `Server-Timing: queue, worker, app` to every response under `timed_prefix` (default `/api/`), logs a request slower than `slow_s` (default 3 s) with where its time went, logs a rate-limited line when more than `inflight_warn` (default 16) requests are in flight, and judges each request class the app declares against a soft and a hard limit ("over budget", "budget breach").
- `TimedExecutor(name, max_workers)` is a thread pool that charges queue and worker time to the request that submitted the work; `default_executor()` is a timed stand-in for the event loop's default pool. One named pool per class of work is how RB5 is met.
- `RequestStats` keeps the in-flight peak over a window and the verdicts per class, for an endpoint that reads counters and starts no work.

```python
from src.request_timing import Budget, BudgetClass, RequestTimingMiddleware, TimedExecutor, default_executor

BUDGETS = (
    BudgetClass("board", "GET", lambda path, query: path == "/api/board", Budget(0.5, 1.5)),
)
app.add_middleware(RequestTimingMiddleware, classes=BUDGETS, budget_overrides=lambda: settings.request_budgets)
asyncio.get_running_loop().set_default_executor(default_executor())   # in the lifespan
HOT_POLL = TimedExecutor("hot-poll", 4)
```

The logger is `request_timing`; a tray-run app attaches its own file handler to it, since a `pythonw` process has no stderr.

## The runtime check

`tests/e2e/budget/_request_budget.py` (manifest key `request_budget_probe`) is the pattern for an adopter's browser tests. On a fake clock (`page.clock`) it loads the main page, lets it settle, then counts every API request by path in three phases:

1. **visible:** one minute with the page visible;
2. **hidden:** one minute after the page fires `visibilitychange` to hidden;
3. **the return:** what the page reads when it becomes visible again.

The clock advances in half-second steps and each step waits for the requests it started to finish, so a self-scheduling poll is measured at its real cadence. The budget: visible at most `[request_budget] visible_requests_per_minute` from the app's `.fleet.toml`, hidden zero, and at most one catch-up read per path.

A page that opens a server-sent event stream (an `EventSource`) holds that request out for as long as it lives, so the probe would never see it settle. Name the stream's path prefixes in `stream_paths` (`measure_request_budget(page, url, stream_paths=("/api/events",))`): a matching request under the `api_prefix` is never waited for, and is counted when it opens, in the phase it opens in. A page that closes its stream on hide and reopens it on return shows up as one catch-up read; a stream the page opens in the hidden minute counts there, and so does one that was open when the page hid and is still open when the minute ends, so a page that keeps its stream while hidden fails the hidden budget of zero. A stream already open when the minute starts is a boot request and is not counted as visible. The visible minute starts only once the page's API requests have been quiet for `BOOT_QUIET_S` (0.5 s of real time, the driver's own `networkidle` window), so an app that boots in two waves, the second starting when the first has answered, is out of both before the count begins; WebKit announces the second wave's requests after the first wave's last `requestfinished`, so "nothing in flight" alone can be the gap between waves. The quiet is measured on the probe's own API requests, so a held stream does not keep it from ending; a page whose API traffic is never quiet for `BOOT_TIMEOUT_S` is unknown. WebKit announces a held stream's request a fraction of a second after the load settles, so with `stream_paths` set the probe waits one real second (`STREAM_BOOT_GRACE_S`) before the visible minute starts; a stream the page opens later is still counted visible.

A count the probe cannot establish is **unknown**, never a pass and never a default: a missing `.fleet.toml`, a missing `[request_budget]` table or key, a value that is not a whole number of 0 or more, a request that never settles, or API traffic that never goes quiet raises `RequestBudgetUnknown` with a `NOT CONFIRMED` message. It is not an `AssertionError`, so pytest reports it as an error (E), apart from a broken budget's failure (F). The probe's unit cases are in `tests/e2e_helpers/test_request_budget_probe.py`.

```python
from tests.e2e.budget._request_budget import assert_request_budget, measure_request_budget, visible_budget

def test_main_page_keeps_its_request_budget(page, base_url):
    reading = measure_request_budget(page, f"{base_url}/")
    assert_request_budget(reading, visible_budget(REPO_ROOT))
```

```toml
[request_budget]
visible_requests_per_minute = 30   # what the main page may read in a visible minute
```

The scaffold's own `tests/e2e/budget/test_vendored_poll.py` runs it on the real helper: a 5 s `startPoll` reads 12 times in a visible minute, never while hidden, and once on the return; a 2 s `setInterval` poll reads 30 times visible and 30 times hidden, and the probe names both breaches.

### Also on WebKit

The local gate's browser slice runs on Chromium; the Mac nightly runs the same suite on WebKit, where timer and poll behaviour differ enough to cross a budget edge. `scripts/tools/webkit_budget_check.py` (manifest key `webkit_budget_check`) is the gate stage that runs the request-budget tests on WebKit locally: the test files that call `measure_request_budget(`, or the files `[webkit_budget] targets` lists when a repo's budget tests share a file with others. It runs with the browser slice and is skipped for an inert-asset (`static`) diff.

Its last line is one verdict, and only `pass` is a pass: `fail` (exit 1) and `unknown` (exit 3, Playwright missing or a declared target absent) fail the gate; `not-installed` (exit 4, no WebKit build here: `python -m playwright install webkit`), `no-tests` (exit 5) and `no-browser-option` (exit 6, the repo's pytest has no `--browser` option because its browser fixtures drive raw `playwright.sync_api` instead of pytest-playwright, so the tests cannot be pointed at WebKit from outside) print `[NOT RUN]` and are never counted as a pass. The option is found by `pytest <targets> --help`, an unanswered probe is `unknown`. A repo that wants the check adds pytest-playwright and moves its fixtures onto it.

## Every limit is a setting

Poll intervals, pool sizes, scan TTLs and concurrency caps are owner settings in the app's Settings, with sensible defaults and a "Light machine" preset, never constants only code can change: a slower computer should be fixable from Settings. The ratchet's floors hold the defaults to a sane range; the middleware reads its budget overrides on every request, so a change applies live. Session or state rows whose process is gone are reconciled out of the hot poll set, so stale history costs no work on every tick.
