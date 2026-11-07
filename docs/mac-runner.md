# Mac Mini self-hosted runner

The fleet's nightly platform pass runs on the Mac Mini as a GitHub Actions self-hosted runner. One runner, registered on `project-scaffolding` only, serves every web app: its workflow, `.github/workflows/nightly-mac.yml`, checks out each public web-app adopter's `main` in turn and runs

- the adopter's e2e suite on **Playwright WebKit with the iPhone projection** (macOS WebKit is far closer to Safari than the Windows build), and
- an **iOS Simulator Mobile Safari smoke** (`scripts/ios_sim_smoke.py`): the adopter's throwaway instance opened in real Mobile Safari on an iPhone simulator, one screenshot per key view.

It is a later stage, not a gate. Each repo's local pre-ship gate stays the per-change contract; the nightly pass audits, on the real engine, what the per-change runs could not reach.

A personal GitHub account has no organization-level runners, and one runner per repo would mean one launchd service per repo on the Mac. Hence one hub runner, with the adopter list in the workflow's matrix.

## Safety

`project-scaffolding` is public, and a self-hosted runner executes whatever a triggering workflow tells it to. The rules, each asserted by `tests/ci/test_nightly_mac_workflow.py`:

- **Triggers are `schedule` and `workflow_dispatch` only.** Never `pull_request`, `pull_request_target` or `push`. Dispatch needs write access to the repo.
- **The job's `if:` refuses everything else**: any other event, any fork pull-request payload, and any copy of the workflow running in a fork (`github.repository` must be this repo).
- **Least privilege**: `permissions: contents: read`, and both checkouts set `persist-credentials: false`.
- **No secrets.** The runner holds only its own registration. Nothing in the workflow reads `secrets.*`.
- **Results stay private.** A public repo's logs and artifacts are public, so the log and the step summary carry pass/fail lines only. Screenshots and failure traces go to `~/mac-nightly-results/<repo>/<run id>/` in the runner user's home, outside every checkout, and nothing is uploaded. Runs older than 14 days are pruned.
- **Fork approval stays on.** Repo Settings → Actions → General → "Approval for running fork pull request workflows from contributors" is set to require approval for all outside contributors. The workflow has no pull-request trigger, so this is depth, not the main line.

Delivering the screenshots to the owner's private channel is not wired: it needs a bot credential, which the runner must not hold. Until that has a home that is not the runner, the images are read on the Mac (or over Screen Sharing).

## Schedule and whisper

The Mac is also a whisper host. The hub places whisper on the gaming PC first, then the Mac, so the nightly pass runs in the quiet hours: cron `0 2 * * *` is **UTC**, which is 03:00 in Madrid in winter (CET) and 04:00 in summer (CEST), inside 02:00–05:00 local either way. Concurrency is 1 at every level: the runner takes one job, the workflow's `concurrency` group queues a second run, and the matrix runs adopters one after another (`max-parallel: 1`). A wedged run is capped at 90 minutes.

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

## Re-register or remove

```sh
bash scripts/mac_runner_setup.sh remove                      # stop, uninstall the service, deregister
RUNNER_TOKEN=<new token> bash scripts/mac_runner_setup.sh install
```

`remove` mints a removal token with `gh api` (or reads `RUNNER_REMOVE_TOKEN`; the web UI's runner page shows one too). It leaves `~/actions-runner` on disk for you to delete. A runner that has been offline for 14 days is removed by GitHub automatically and needs a fresh `install`.

## Adding an adopter

Add one `include:` entry to the workflow's matrix: the repo name, its Python, its requirements files, the folder of its committed `*.sample.*` config twins, its e2e target plus flags, and the key views the smoke opens. The adopter must be public and must declare `[design.review.synthetic] command` in its `.fleet.toml`: the throwaway, engine-off instance the smoke boots. That command prints `URL=<base>` once the instance answers and stops when its stdin closes; the smoke reports `SMOKE=unknown` (exit 3, a failing state, never a pass) when it is missing.

## Smoke results

`scripts/ios_sim_smoke.py` ends with one line:

| Line | Exit | Meaning |
|---|---|---|
| `SMOKE=pass shots=<n>` | 0 | every view opened in Mobile Safari and produced a screenshot |
| `SMOKE=fail reason=...` | 1 | a view did not open or gave no usable screenshot |
| `SMOKE=unknown reason=...` | 3 | a prerequisite is missing: no `simctl`, no iPhone simulator, no synthetic command, or the instance never printed its URL |

A pass proves Mobile Safari reached the instance and painted something for each view; whether the page looks right is read from the screenshots.
