# Mac Mini self-hosted runner

The Mac Mini nightly is the fleet's one CI (decision: [architecture-decisions.md](architecture-decisions.md), "The Mac Mini nightly is the fleet's one CI"). It runs as a GitHub Actions self-hosted runner. One runner, registered on `project-scaffolding` only, serves every adopter: its workflow, `.github/workflows/nightly-mac.yml`, checks out the `main` of each public adopter that changed since its last green night (every adopter on Sunday) and runs, in order,

- the adopter's **unit suite**, with Windows-only tests excluded by marker;
- its e2e suite on **Playwright WebKit with the iPhone projection** (macOS WebKit is far closer to Safari than the Windows build); and
- an **iOS Simulator Mobile Safari smoke** (`scripts/ios_sim_smoke.py`): the adopter's throwaway instance opened in real Mobile Safari on an iPhone simulator, one screenshot per key view.

Each leg is optional per adopter, and a failed test is retried once (see "Legs and retries"). The nightly is not a merge gate. Each repo's local pre-ship gate stays the per-change contract, and the nightly checks what landed on `main`, on the real engine.

A personal GitHub account has no organization-level runners, and one runner per repo would mean one launchd service per repo on the Mac. Hence one hub runner: the adopter list is `.github/nightly-adopters.txt` in this repo, and each adopter's settings are the `[ci.nightly]` table in its own `.fleet.toml`.

## Safety

`project-scaffolding` is public, and a self-hosted runner executes whatever a triggering workflow tells it to. The rules, each asserted by `tests/ci/test_nightly_mac_workflow.py`:

- **Triggers are `schedule` and `workflow_dispatch` only.** Never `pull_request`, `pull_request_target` or `push`. Dispatch needs write access to the repo.
- **Every job's `if:` refuses everything else**: any other event, any fork pull-request payload, and any copy of the workflow running in a fork (`github.repository` must be this repo).
- **Least privilege**: `permissions: contents: read`, and every checkout sets `persist-credentials: false`.
- **No secrets.** The runner holds only its own registration. Nothing in the workflow reads `secrets.*`.
- **Adopter settings are data, not script.** An adopter's `[ci.nightly]` values reach the steps as environment variables, never as `${{ }}` text inside a `run:` script, and `scripts/nightly_matrix.py` refuses any value outside a conservative character set (no spaces, quotes, `$`, backticks, `;`, `|`, `&`, redirects or globs), so a table cannot inject a command.
- **Anonymous reads only.** The selection job reads each adopter's `main` with a shallow `git fetch` over HTTPS, with no credential helper and no prompt; an adopter must be public.
- **Results stay private.** A public repo's logs and artifacts are public, so the log and the step summary carry pass/fail lines only. Screenshots, failure traces, junit files and flaky test ids go to `~/mac-nightly-results/<repo>/<run id>/` in the runner user's home, outside every checkout, and nothing is uploaded. Runs older than 14 days are pruned.
- **Fork approval stays on.** Repo Settings → Actions → General → "Approval for running fork pull request workflows from contributors" is set to require approval for all outside contributors. The workflow has no pull-request trigger, so this is depth, not the main line.

Delivery is covered under "Delivering results" below.

## Delivering results

The images reach the owner's chat without any delivery credential on the runner. Delivery is **pull-only**, run by a scheduled `local-llm-hub` job on the trusted hub host:

1. The workflow's last step writes `READY` in the run folder (the fields under "The `READY` marker", nothing else), by write-then-rename so it is never half-written.
2. The hub job lists run folders that have `READY`, skips the run ids it has already delivered, copies the `*.png` files over SSH, and sends them to the owner's chat with `send_file.py`.
3. The hub records the delivered run id in its own store. Nothing is written back to the Mac, which keeps its plain 14-day prune.

Contract the puller keeps:

- **Its key is forced-command and read-only.** The runner user's `authorized_keys` entry for the hub restricts the command to listing run folders and reading `*.png` from a run, with no shell, no write, no port or agent forwarding and no pty. The hub holds the private key; nothing on the runner can use it.
- **The pull window is shorter than the prune.** The job only considers runs newer than a few days (well under the 14-day prune), so a run is never pulled while it is being deleted.
- **A run folder is untrusted data.** Adopter code produced it, so the puller takes only regular `*.png` files under a size cap and a count cap, ignores symlinks and any other name, and never executes or interprets a file's content.
- **Nothing leaves the Mac by the workflow.** It makes no outbound call except anonymous read-only fetches of public adopters, uploads nothing and reads no `secrets.*`; a fork pull request cannot start it, and it has no path to the puller. Host addresses, logins and keys live in the hub's own configuration, never in this repo, a log or an artifact.
- **Unknown stays unknown.** An unreachable Mac, a run without `READY` or a send that is not confirmed is reported as such and retried on the next pass; a run id is recorded as delivered only after a confirmed send.

The puller itself is tracked in `local-llm-hub`; this repo owns the folder layout and the `READY` marker above.

## Schedule and whisper

The Mac is also a whisper host. The hub places whisper on the gaming PC first, then the Mac, so the nightly pass runs in the quiet hours: cron `23 1 * * *` is **UTC**, which is 02:23 in Madrid in winter (CET) and 03:23 in summer (CEST), inside 02:00–05:00 local either way and, with the 90-minute cap, finished by 04:53. The minute is off `:00` because GitHub delays or drops scheduled runs at the start of the hour. Concurrency is 1 at every level: the runner takes one job, the workflow's `concurrency` group queues a second run, and the matrix runs adopters one after another (`max-parallel: 1`). A wedged run is capped at 90 minutes.

### Fallback trigger

GitHub's `schedule` trigger has not created a run for this workflow on any night, whatever the cron minute, so a PC-side job also starts it. `scripts/nightly_mac_fallback.py` runs `gh workflow run nightly-mac.yml --ref main` once a night, at 02:23 local, from a daily app-launcher Job. It needs `gh` logged in with write access to the repo, which the PC already has; the Mac never holds a GitHub token.

It lists the workflow's recent runs first and does nothing when one of any event was already created for today's UTC date, so a schedule that starts working never doubles up. Each path ends in one log line:

| Outcome | Log line starts | Exit |
| --- | --- | --- |
| Dispatched, and a run for today appeared within a minute | `✅ dispatched` | 0 |
| A run for today already exists | `ℹ️ skipped` | 0 |
| `gh` failed (not found, not logged in, offline, dispatch refused) | `❌ gh failed` | 1 |
| Dispatch accepted but no run appeared in time | `⚠️ not confirmed` | 3 |

The skip only protects the cron slot when the fallback runs second. From the last Sunday of October to the last Sunday of March (CET) 02:23 local is 01:23 UTC, the cron slot itself. In summer (CEST) it is 00:23 UTC, an hour before the slot, so a schedule that works would then add a second run behind the fallback's (the `concurrency` group queues it): move the Job to 03:23 for the summer, or drop it once the schedule is proven.

The Job entry, as a committed example (`launcher.py` registers it through `POST /api/jobs` or the Jobs tab, never by a hand edit of `config/jobs.json`):

```json
{
  "id": "nightly-mac-fallback",
  "name": "nightly-mac fallback trigger (02:23)",
  "script_path": "E:\\automation\\project-scaffolding\\scripts\\nightly_mac_fallback.py",
  "args": "",
  "schedule": { "type": "daily", "at": "02:23" },
  "alert_on_failure": true,
  "rerun_safe": true
}
```

`rerun_safe` holds because a second run the same day skips.

### Speech-to-text latency during a run

What the Mac serves is the hub's `audio_transcribe` role: parakeet on the Neural Engine, with whisper only as the fallback when parakeet is down. `scripts/audio_latency_probe.py` measures it through the hub's audio route only: `probe` sends short synthetic tone clips (no recording of anyone) at a fixed spacing and records each round trip with the host and model that served it, and `compare` judges a during-run window against a baseline. Negligible means up to +10 % at p95 plus 150 ms; anything unestablished (a failed request, fewer than 20 samples, a different serving host or model) is `unknown`, exit 3, never a pass.

Measured on a manual `workflow_dispatch` run of the one current adopter (the job took 2 min 22 s), 4 s clips every 5 s, all served by the Mac's parakeet and all answered 200:

| Window | Clips | p50 | p95 | Max |
|---|---|---|---|---|
| Baseline, Mac idle | 40 | 350 ms | 382 ms | 414 ms |
| During the job | 23 | 316 ms | 6,355 ms | 6,763 ms |

The median does not move; the tail does. The six slow requests (1.3 s to 6.8 s) all fall inside the WebKit e2e leg; the dependency install before it and the simulator smoke after it show none, and the 77 clips outside the job window are all fast. A run therefore delays speech-to-text by seconds while its WebKit suite runs, which is far past the +10 % bound, so the quiet-hours schedule above is the mitigation and stays. A "yield to whisper" check before starting would need the workflow to call the hub, and the workflow makes no outbound call. A manual dispatch during the day shows the same delay, so run it when nobody is dictating.

Re-measure after any change to the runner's concurrency, an adopter's suite, or the hub's placement of the transcribe role:

```sh
python scripts/audio_latency_probe.py probe --label baseline --count 40 --interval-s 5 --out baseline.json
# start a run, then probe across it
python scripts/audio_latency_probe.py probe --label during --count 100 --interval-s 5 --out during.json
python scripts/audio_latency_probe.py compare baseline.json during.json --from <job start, unix> --to <job end, unix>
```

## Mac prerequisites

Done once, from an admin account:

1. **Xcode** from the App Store (or `xcodes`), then:
   ```sh
   sudo xcode-select -s /Applications/Xcode.app
   sudo xcodebuild -license accept
   sudo xcodebuild -runFirstLaunch
   xcodebuild -downloadPlatform iOS     # the iOS simulator runtime
   ```
2. **Homebrew**, then `brew install python gh node`. Python runs the smoke script and builds each adopter's `.venv` (the workflow's `actions/setup-python` installs the exact version an adopter pins); `gh` mints the registration token and checks status; Node is for a future JavaScript adopter and is not needed by the Python ones.
3. **A dedicated standard (non-admin) user** for the runner, e.g. `ghrunner`. The runner executes adopter code, so it gets no admin rights and no personal data.
4. **Automatic login for that user**: System Settings → Users & Groups → "Automatically log in as" → the runner user. The runner installs as a LaunchAgent, which starts in the user's GUI session, and the iOS Simulator needs that session. Automatic login is unavailable while FileVault is on; with FileVault on, log the runner user in by hand after each reboot.
5. Disable sleep for the Mac (System Settings → Energy → "Prevent automatic sleeping when the display is off").
6. **A writable `/Users/runner`**, from an admin account:
   ```sh
   sudo mkdir -p /Users/runner && sudo chown <runner-user> /Users/runner
   ```
   `actions/setup-python` on macOS ignores `AGENT_TOOLSDIRECTORY` and always installs into `/Users/runner/hostedtoolcache` (the hosted images' user). Without the folder every run fails in the `setup-python` step with `mkdir: /Users/runner: Permission denied`.

## Registration token

A registration token is valid for one hour and registers one runner. Get one from either:

- the web UI: repo **Settings → Actions → Runners → New self-hosted runner**, macOS, ARM64; the token is in the `config.sh` line shown there; or
- the CLI, from any machine where `gh` is logged in with admin on the repo:
  ```sh
  gh api -X POST repos/ferraroroberto/project-scaffolding/actions/runners/registration-token --jq .token
  ```

Minting it elsewhere and passing it in keeps the runner user free of a GitHub login.

## Install with the script

As the runner user, in its GUI session, from a checkout of this repo:

```sh
RUNNER_TOKEN=<token> bash scripts/mac_runner_setup.sh install
```

`scripts/mac_runner_setup.sh install` checks for macOS arm64, `simctl` and an iPhone simulator (it creates one for this user when the runtime is installed but the user has no device), downloads the latest `actions/runner` macOS arm64 release, verifies its SHA-256 against the release notes, registers it with `config.sh`, installs and starts the service, and prints its status. Without `RUNNER_TOKEN` it mints the token with `gh api` (that needs a `gh` login with admin; `gh auth logout` afterwards). `RUNNER_REPO`, `RUNNER_NAME` and `RUNNER_DIR` override the repo, the name (`mac-mini`) and the folder (`~/actions-runner`).

## Install by hand

The same steps, for when the script is not at hand:

```sh
mkdir -p ~/actions-runner && cd ~/actions-runner
# download + extract the osx-arm64 tarball named on the "New self-hosted runner" page
./config.sh --unattended --url https://github.com/ferraroroberto/project-scaffolding \
  --token <token> --name mac-mini --labels iphone-sim --work _work
./svc.sh install
./svc.sh start
./svc.sh status
```

The runner adds `self-hosted`, `macOS` and `ARM64` itself, and labels match case-insensitively, so the workflow's `runs-on: [self-hosted, macos, arm64, iphone-sim]` needs only the one custom label.

A runner registered without `--labels iphone-sim` (for example by following the "New self-hosted runner" page, which does not ask for labels) shows only `self-hosted`, `macOS` and `ARM64`, and every `nightly-mac` run queues forever. Add the label afterwards, from any machine with a `gh` login that has admin on the repo, with no re-registration:

```sh
gh api repos/ferraroroberto/project-scaffolding/actions/runners --jq '.runners[] | "\(.id) \(.name)"'
gh api -X POST repos/ferraroroberto/project-scaffolding/actions/runners/<id>/labels -f "labels[]=iphone-sim"
```

`gh api -X DELETE repos/ferraroroberto/project-scaffolding/actions/runners/<id>/labels/iphone-sim` removes it again.

## Check it is online

- `bash scripts/mac_runner_setup.sh status` prints the launchd state and, with a `gh` login, GitHub's view (`online`, `busy`, labels).
- Or repo Settings → Actions → Runners: `mac-mini` shows **Idle**.
- Or from any machine: `gh api repos/ferraroroberto/project-scaffolding/actions/runners`.

Then run the workflow once by hand: Actions → `nightly-mac` → "Run workflow", or `gh workflow run nightly-mac.yml -R ferraroroberto/project-scaffolding`. A queued run that never starts means no runner with all four labels is online.

## Remote (SSH) setup

A runner that is registered but offline can be brought back from another machine, with no login at the Mac, as long as the runner user is logged in at the console (auto-login, below). Over SSH as the runner user:

```sh
cd ~/actions-runner && ./svc.sh status      # "not installed" means it was only ever started by hand
./svc.sh install && ./svc.sh start && ./svc.sh status
```

A runner started with `./run.sh` is not a service: it goes offline when that terminal closes. `svc.sh` installs a **LaunchAgent**, which starts only once the runner user is logged in, so a reboot recovers the runner only if the Mac auto-logs-in that user. Check both from the same SSH session:

```sh
defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser   # prints the user when auto-login is on
pmset -g | grep -E '^ *(sleep|displaysleep|autorestart)'                  # sleep 0, autorestart 1
```

Auto-login is turned on in System Settings → Users & Groups → Automatically log in as, which needs the user's password, so it is a step at the Mac, not over SSH. `sudo pmset -a sleep 0 disablesleep 1` covers the sleep prerequisite. The registered name is whatever the registration used (a UI-registered runner is named after the user, not `mac-mini`); the workflow selects on labels only.

## Re-register or remove

```sh
bash scripts/mac_runner_setup.sh remove                      # stop, uninstall the service, deregister
RUNNER_TOKEN=<new token> bash scripts/mac_runner_setup.sh install
```

`remove` mints a removal token with `gh api` (or reads `RUNNER_REMOVE_TOKEN`; the web UI's runner page shows one too). It leaves `~/actions-runner` on disk for you to delete. A runner that has been offline for 14 days is removed by GitHub automatically and needs a fresh `install`.

## Routing audit

The per-change gate routes e2e with `classify_e2e` (skip, static, surface or full), so the nightly full WebKit run is the check on that routing: a failure on a night whose merged commits were routed `skip`, or `static` for a node outside the declared `static_pytest_target`, means the adopter's `[e2e]` rules are too narrow. `scripts/routing_audit.py` has two halves split by trust.

**`audit` (runner, no network).** It runs after the e2e and smoke legs of an adopter that declares `e2e`, even when they failed, and reads the adopter checkout (full history), the pytest junit file and a state file in the runner user's home, `mac-nightly-results/<repo>/audit-state.json`, which holds the last green commit. It writes `audit.json` into the run folder and appends one line to the step summary, counts only: `Routing audit: nights audited N, misses found M`.

| Line | Exit | Meaning |
|---|---|---|
| `AUDIT=clean nights=1 misses=0` | 0 | a green night, or a red one whose window routing covered |
| `AUDIT=miss nights=1 misses=N` | 1 | N failing nodes on commits routing would not have run them for |
| `AUDIT=unknown nights=0 reason=...` | 3 | the night could not be measured |

A green night advances the state to the adopter's `HEAD`. A red or unknown night leaves it, so the next night audits the longer window since the last green one. Each first-parent commit in that window is classified with the adopter's current `[e2e]` table (a shared stylesheet counts as full, which can only hide a miss, never invent one). Any commit routed `skip` makes every failing node a miss; otherwise a `static` commit makes the failing nodes outside `static_pytest_target` a miss. A failure when every commit routed `surface` or `full` is not a miss: routing ran the suite.

`unknown` is its own state, never folded into clean: the e2e leg was skipped or cancelled, the junit file is missing or has no failing test under a failed leg, the adopter's `[e2e]` table is missing or unusable, there is no earlier green night yet (the first run only records a baseline when it is green), the last green commit is gone from the history, git cannot list the window, or a failing node sits in a module that cannot be located on disk under a `static` change.

**`file` (trusted host, needs `gh`).** `python scripts/routing_audit.py file --audit <audit.json>` reads a pulled `audit.json` and files nothing unless it records a miss. For a miss it keeps exactly one open issue in the adopter titled `e2e routing: nightly audit found a miss`, labelled `bug`: it creates it, or comments on the open one only when the failing-node set changed (a hidden marker holds the set's digest). The body carries the failing node ids, the tier counts and an acceptance checklist, nothing else. `audit.json` is untrusted data (adopter code named the nodes), so the tool checks its shape and size, strips backticks and control characters, and prints node ids inside a code fence. It ends on `FILE=none|created|commented|unchanged`, or `FILE=unknown` (exit 3) when `gh` could not confirm. `--dry-run` prints the body. The runner holds no `gh` or token; the pull job in `local-llm-hub` runs `file` after it copies a run that has `READY`.

## Adding an adopter

1. Add a `[ci.nightly]` table to the adopter's `.fleet.toml` and merge it to its `main` (nothing reads it until step 2).
2. Add the repo's name as one line in this repo's `.github/nightly-adopters.txt`.

The adopter must be public: the selection job reads it anonymously. When it declares `views`, it must also declare `[design.review.synthetic] command` in its `.fleet.toml`: the throwaway, engine-off instance the smoke boots. That command prints `URL=<base>` once the instance answers and stops when its stdin closes; the smoke reports `SMOKE=unknown` (exit 3, a failing state, never a pass) when it is missing.

### The `[ci.nightly]` table

```toml
[ci.nightly]
python         = "3.14"                                     # required: the version setup-python installs
requirements   = ["requirements.txt", "requirements-dev.txt"]  # required: installed into a fresh .venv
samples        = "config"                                   # optional: folder of committed *.sample.* config twins
unit           = ["tests", "--ignore=tests/e2e"]            # optional: pytest arguments for the unit leg
e2e            = ["tests/e2e", "--e2e-autoboot"]            # optional: pytest arguments for the WebKit e2e leg
views          = ["/"]                                      # optional: key views for the simulator smoke (needs e2e)
exclude_marker = "not windows_only"                         # optional: the unit leg's -m expression (this is the default)
```

At least one of `unit` and `e2e` is required. A repo that is listed but cannot run here declares only `skip_reason = "<why>"`, and the selection summary shows the reason every night. Unknown keys are refused, so a typo is an error, not a silently ignored setting.

Tests that need the tray, toasts, PowerShell, real audio devices or other Windows-desktop state carry `@pytest.mark.windows_only` (the marker is registered in the adopter's `pytest.ini`) and are excluded from the unit leg. They are not ported: the local gate keeps covering them, and the PR that marks them lists them.

A listed repo whose `main` cannot be fetched, or whose table is missing or refused, is not dropped: it gets a matrix row marked unknown, its job fails at once with the reason, and its `READY` says `result=unknown`.

### Selection and state

The `select` job runs `scripts/nightly_matrix.py build`: for each listed repo it reads the `main` commit and `.fleet.toml` from one shallow fetch (so the settings always belong to the commit that gets tested) and compares that commit with `last_green_sha` in `~/mac-nightly-results/<repo>/state.json`.

- **Weekdays:** a repo runs only when its `main` differs from its last green SHA. A repo with no green night yet always runs.
- **Sunday** (the run's UTC date) **or a dispatch with `full: true`:** every repo runs.
- **Nothing changed:** the platform job is skipped, and the selection summary says no repo runs tonight. That is a clean night, not a failure.

The platform job checks out the exact commit the selection read. Only a green night moves `last_green_sha` (write-then-rename). A red or unknown night leaves it, so a red `main` runs again every night until it goes green. `audit-state.json` beside it belongs to the routing audit and keeps its own meaning.

### Legs and retries

`scripts/nightly_matrix.py leg` runs the unit leg and the e2e leg. Each runs pytest once; on a failure it runs `--last-failed` once more.

| Leg result | Meaning |
|---|---|
| `pass` | the first run passed |
| `flaky` | the first run failed and the retry passed; the test ids are in `unit-flaky.txt` or `e2e-flaky.txt` in the run folder |
| `fail` | the retry failed too, or the first run passed the one-hour cap (no second hour is spent) |
| `unknown` | pytest collected nothing |
| `not-run` | the adopter does not declare the leg, or an earlier step (install, config seeding) failed |

The night is `green` when no leg is `fail`, no declared leg is `not-run` and no declared leg is `unknown`. A flaky leg is green: the flake is recorded, never hidden. Each leg runs even when the one before it failed, so one red leg does not hide another. The routing audit reads the e2e leg's first-attempt `junit.xml`.

### The `READY` marker

One `key=value` per line, every value a single token:

| Key | Value |
|---|---|
| `run` | the Actions run id |
| `repo` | the adopter |
| `sha` | the commit tested, or `unknown` |
| `result` | `green`, `red` or `unknown` |
| `unit`, `e2e`, `smoke` | `pass`, `flaky`, `fail`, `not-run` or `unknown` |
| `flaky` | how many tests passed only on the retry |
| `audit` | the routing audit's `clean`, `miss` or `unknown`, or `not-run` |

No logs, paths, test names or images. The test ids behind `flaky` stay in the run folder.

## Smoke results

`scripts/ios_sim_smoke.py` ends with one line:

| Line | Exit | Meaning |
|---|---|---|
| `SMOKE=pass shots=<n>` | 0 | every view opened in Mobile Safari and produced a screenshot |
| `SMOKE=fail reason=...` | 1 | a view did not open (after one retry of `openurl`, which the first command on a just-booted simulator can time out) or gave no usable screenshot |
| `SMOKE=unknown reason=...` | 3 | a prerequisite is missing: no `simctl`, no iPhone simulator, no synthetic command, or the instance never printed its URL |

A pass proves Mobile Safari reached the instance and painted something for each view; whether the page looks right is read from the screenshots.
