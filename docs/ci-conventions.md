# CI conventions

Moved verbatim from `CLAUDE.md` (`#254`) so the always-on file stays under its size cap. `CLAUDE.md` keeps each section's heading, its *apply only if* gate and one-line rules, and points here for the full procedure, reasoning, snippets and decision records. Headings match `CLAUDE.md`'s, so a reference to a section by name resolves in either file.

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

**Sister-repo tracking:** a repo still on the old runner/actions (`#25`) or duplicate `push`-on-branches trigger (`#38`) gets a pointer issue back to `project-scaffolding`'s canonical record. Fix before the deprecation deadline.

**A red default branch files its own tracking issue — `main-gate-watch`.** Copy `.github/workflows/main-gate-watch.yml.template` → `.github/workflows/main-gate-watch.yml`, replace `__GATE_WORKFLOW_NAME__` with the gate workflow's `name:`. On `workflow_run` completion for that workflow (filtered `branches:[main]`, PR runs excluded, gated on `conclusion=='failure'`): creates label `ci-red-main` (`--force`, idempotent), comments `Still red on main at <sha>: <run-url>` on the open `ci-red-main` issue, or files `main's <gate> gate is red` (`bug`+`ci-red-main`, assigned to `github.repository_owner`) if none open. Issue stays open until `main` is green; discounting a red gate for an unrelated PR does not close it. Without this, a red `main` is nobody's finding (`whatsapp-radar#258`; three repos found red same day, 2026-08-15).

- **Precondition:** a `workflow_run` watcher can only observe a gate that runs in Actions on pushes to the default branch. A repo whose gate is local-only (`verify-before-ship.ps1`/`pytest` on-machine — *this scaffold included*) gets **zero** coverage — don't install the watcher there. Its red-`main` detection is **unknown**, reported as its own state, never folded into green.
- **Local-gate repos get a scheduled fleet-side sweep instead, not an advisory Actions gate** (`#222`) — a ported Windows-desktop gate on a hosted runner is a degraded subset, and a green watcher over it is false coverage. So: watcher where Actions runs the real gate; scheduled sweep of the actual local gate elsewhere — both file the same idempotent `ci-red-main` issue; a gate that can't run reports `unknown` with a reason. Sweep belongs in `fleet-config` as its own scheduled skill (not bolted onto `/audit-fleet`, whose bounded weekly cost depends on no per-repo workloads); **unbuilt** — until it exists, local-gate repos have no automated detection and should say so.

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
