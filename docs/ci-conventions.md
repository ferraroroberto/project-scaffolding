# CI conventions

Moved verbatim from `CLAUDE.md` so the always-on file stays under its size cap. `CLAUDE.md` keeps each section's heading, its *apply only if* gate and one-line rules, and points here for the full procedure, reasoning, snippets and decision records. Headings match `CLAUDE.md`'s, so a reference to a section by name resolves in either file.

## GitHub Actions CI conventions
*Apply whenever this project adds a `.github/workflows/` file.*

- **Pin a dated Windows runner:** `runs-on: windows-2025`, never `windows-latest` (GitHub redirects `windows-latest`→`windows-2025`, deadline June 2026) — an OS image change must not silently flip a green gate red.
- **Use Node-24 action majors:** `actions/checkout@v6`, `actions/setup-python@v6`, `actions/upload-artifact@v7` — not `checkout@v4` / `setup-python@v5` / `upload-artifact@v4` (deprecated Node 20; forced Node 24 from June 16 2026, Node 20 removed September 16 2026). Drop-in, inputs unchanged.
- **Trigger once per commit: `push:[main]` + `pull_request:[main]`.** Do **not** trigger `push` on feature branches (no `branches:` filter, or `branches-ignore:[main]`): with a PR open both events fire and the gate runs **twice on the same commit**; `branches-ignore:[main]` also *omits* the post-merge `main` gate. `concurrency` can't fix it (`github.ref` differs: `refs/heads/<branch>` vs `refs/pull/<N>/merge`). Non-loss: CI on a branch pushed but never PR'd — `/issue-finish` always pushes then immediately opens the PR.
- **Run counts, wrong shape → this convention:** feature-branch push with open PR **2→1**; no PR yet **1→0** (open the PR before you need CI); merge commit on `main` **0→1**.

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

**Sister-repo tracking:** a repo still on the old runner/actions or duplicate `push`-on-branches trigger gets a pointer issue back to `project-scaffolding`'s canonical record. Fix before the deprecation deadline.

**A red default branch files its own tracking issue — `main-gate-watch`.** Copy `.github/workflows/main-gate-watch.yml.template` → `.github/workflows/main-gate-watch.yml`, replace `__GATE_WORKFLOW_NAME__` with the gate workflow's `name:`. On `workflow_run` completion for that workflow (filtered `branches:[main]`, PR runs excluded, gated on `conclusion=='failure'`): creates label `ci-red-main` (`--force`, idempotent), comments `Still red on main at <sha>: <run-url>` on the open `ci-red-main` issue, or files `main's <gate> gate is red` (`bug`+`ci-red-main`, assigned to `github.repository_owner`) if none open. Issue stays open until `main` is green; discounting a red gate for an unrelated PR does not close it. Without this, a red `main` is nobody's finding.

- **Precondition:** a `workflow_run` watcher can only observe a gate that runs in Actions on pushes to the default branch. A repo whose gate is local-only (`verify-before-ship.ps1`/`pytest` on-machine — *this scaffold included*) gets **zero** coverage — don't install the watcher there. Its red-`main` detection is **unknown**, reported as its own state, never folded into green.
- **Local-gate repos get a scheduled fleet-side sweep instead, not an advisory Actions gate** — a ported Windows-desktop gate on a hosted runner is a degraded subset, and a green watcher over it is false coverage. So: watcher where Actions runs the real gate; scheduled sweep of the actual local gate elsewhere — both file the same idempotent `ci-red-main` issue; a gate that can't run reports `unknown` with a reason. Sweep belongs in `fleet-config` as its own scheduled skill (not bolted onto `/audit-fleet`, whose bounded weekly cost depends on no per-repo workloads); **unbuilt** — until it exists, local-gate repos have no automated detection and should say so.

## Web-app CI template
*Apply when a web app (FastAPI, Streamlit, Flask, a static PWA) with a Playwright e2e suite adopts GitHub Actions CI.*

`.github/workflows/ci.yml.template` is the canonical gate, derived from the e2e workflows that run green on the hosted runner (`voice-transcriber`, `whatsapp-radar`, `app-launcher`). It follows every rule in "GitHub Actions CI conventions" above. One job, `gate`, on `windows-2025`:

1. fresh `.venv` from the requirements files (every native call exit-code-checked, since a PowerShell step only fails on its *last* command);
2. `playwright install chromium webkit`;
3. seed each gitignored `config/*.sample.*` to its live name when absent;
4. unit suite (`pytest --ignore=tests/e2e`);
5. e2e on desktop chromium;
6. e2e on a phone projection (`webkit` + `--device "iPhone 13"`, only tests marked `phone`; "no test collected" is surfaced as a `::warning::` annotation, never a silent pass);
7. upload `test-results*` (trace + screenshot, `retention-days: 7`) **only on failure**.

It is quiet by design: `permissions: contents: read`, no secret, no third-party service. `tests/test_ci_template.py` asserts those properties on the template itself.

**Adopt in one PR:**

1. Copy it to `.github/workflows/ci.yml` and change only the `# ADAPT:` lines: Python version, requirements files (add `-r requirements-dev.txt` if test deps are split), the unit command, the e2e directory, the seed directory, and `timeout-minutes` (≈4× the typical green run). Delete the phone step for a repo with no phone-first surface; otherwise register the `phone` marker in the pytest config (`markers = ["phone: needs the phone viewport or WebKit engine"]`).
2. Add the `## CI expectations` block to the repo's `CLAUDE.md` (template above): workflow `ci.yml`, job `gate`, typical duration, the phone step as the flaky leg, the e2e-surface paths.
3. Optionally install `main-gate-watch` with `__GATE_WORKFLOW_NAME__` = `ci` (the precondition above holds: this gate runs on pushes to `main`).
4. Lint it: `actionlint .github/workflows/ci.yml` (PyPI `actionlint-py` ships the binary: `pip install actionlint-py`).
5. **Done means green on the first PR and on `main` for 5 consecutive runs.** A first-PR red is a CI-safety bug in the repo's tests, fixed in that PR, not worked around in the workflow.

**Making tests CI-safe** (a clean runner has none of your machine's state):

- **Fixtures, not live state.** A test reads committed fixture or demo data, never a developer's real database, token, account or `data/` folder. A gitignored config is replaced by its committed `*.sample.*`; the sample carries no credential, and loopback traffic bypasses auth middleware.
- **Missing optional state skips, never fails.** `pytest.skip("reason")` with a message that names what was absent, not a bare `assert` on a file a clone does not have. A skip that silently disables a whole authed suite is its own defect: seed the sample so the suite runs.
- **Wait on conditions, not timeouts.** Playwright auto-waiting and `expect(...)` assertions, `wait_for_response`, `wait_for_function`; never `time.sleep` or a fixed `wait_for_timeout`. The hosted runner is slower than a dev box, so a fixed sleep is a flake waiting for load. Widen budgets through one environment variable (`E2E_DEFAULT_TIMEOUT_MS`), not per test.
- **Boot a disposable instance on a fixed e2e port** and refuse an occupied one unless the loudly-named opt-in is set (see "End-to-end UI testing"); a boot failure is a hard failure, never `pytest.skip`.
- **No Windows-desktop dependency in the CI path** (tray, toast, real audio device): mark those tests and exclude them from the CI command rather than porting a degraded gate.

**Out of scope:** CLI and library repos with no web app; fixing a repo's existing reds (tracked in that repo).

## CI is advisory — `## CI expectations` block + e2e-surface skip rule
*Apply whenever this project has a `.github/workflows/` file **and** a local verification gate.*

**CI is advisory, not a required gate.** Fleet e2e workflows run on repos with **no branch protection**, so checks aren't required to merge; the **local gate** (`scripts/verify-before-ship.ps1`, or `pytest + ruff + mypy`) is the contract. Never treat `gh pr checks --watch` as a mandatory blocking wall.

**CI's only signal beyond the local gate is the e2e suite** — the local gate runs `pytest + ruff + mypy` but skips the Playwright leg (needs browsers + live webapp; also the known-flaky part on the slower hosted Windows runner). A diff touching **none** of the project's e2e surface gains nothing from waiting on CI; a wedged WebKit browser can block the merge up to `timeout-minutes`.

**Each project declares a `## CI expectations` block in its own `CLAUDE.md`** (per-project instance: durations, flaky leg, e2e-surface paths). `/issue-finish` reads it; don't inline these values into the skill. Template (fill bracketed values):

```markdown
## CI expectations
- Workflow `[.github/workflows/e2e.yml]`, job `[verify-before-ship]`, on every PR. **Advisory, not required** (no branch protection) — the local gate is the contract.
- Typical green: **~[N] min**. Investigate at **>[2N] min**; treat as wedged at **>[~4N] min**.
- Flaky leg: `[the Playwright WebKit/iPhone projection / PTY-input tests]` can wedge on the hosted runner. `timeout-minutes: [30]` caps a wedge. A wedge is a flake, not the diff.
- CI's only signal beyond the local gate is the **e2e suite** (skipped locally). Its e2e surface = `[app/webapp/, app/tray/, tests/e2e/, static assets, …]`. A diff touching **none** of these gains nothing from CI.
```

**What `/issue-finish` does with it:**
- **Skip-the-wait keyed on e2e surface, not "docs vs code."** No declared e2e surface touched + local gate green → merge on local-green and **state it** in the finish summary (e.g. `CI not awaited — store-only diff, no e2e surface touched`). Generalizes the old `*.md`-only skip rule.
- **Proactive flake handling.** Read expected duration from the block; at the *investigate* threshold, inspect the run (`gh run view --job`), classify flake vs real failure; for the *documented* flaky leg, cancel + rerun **once** automatically, stating so. Second flake → stop, surface to user. **Never** rerun a real failure.
- **Keep-the-human-in-control.** Always **state** the CI decision (skip/wait, any rerun) in the finish summary. Auto-rerun capped at **once**, only for the documented flaky leg. No force-merge; CI advisory means no `--admin` needed. **If a repo later makes `e2e` a *required* status check, fall back to watching** — a required check can't be skipped without `--admin` (out of scope).

**Where each piece lives:** convention + block template here; skill mechanism in `fleet-config` `skills/issue-finish/SKILL.md` step 5; per-project instances in each project's block; sister-repo pointer issues (start: `whatsapp-radar`, `app-launcher`) track adoption. Fixing the e2e leg's flakiness is a separate per-project task — this convention makes a flake cheap, not cured.

## Box load lock — a CPU burn never overlaps a gate

A red-under-load proof saturates the shared box, and a browser gate running at the same moment goes red on page-load timeouts that have nothing to do with its diff. `fleet-config` owns a box-wide advisory lock (`skills/_lib/box_lock.py`, reached through `~/.claude/skills/_lib/`): gates hold it in **shared** mode (many run together), a burn holds it **exclusively** (it runs alone).

- **The gate holds it for its whole run.** `scripts/verify-before-ship.ps1` re-runs itself under `box_lock.py run --mode shared --repo <name> -- <gate>`; the `VERIFY_BOX_LOCK_HELD` environment variable marks the inner run so it goes straight to the stages. The run exits with the gate's own code, or `3` when a burn held the lock past the 30-minute default timeout (the gate itself only ever exits `0` or `1`).
- **No helper, no lock, loud warning.** A machine without the helper (a CI runner, a fresh clone) prints a `[WARN]` line and runs the gate unlocked; a missing helper never fails the gate.
- **A repo's own gate adopts the same wrapper.** Wrap the gate command in the `box_lock.py run` call above, skipping the wrapper with a warning when the helper is absent.