# Architecture decisions

The register of every standing architecture decision in the fleet. Read it before building: if a decision here covers what you are about to do, follow it. For a human-readable tour of what each app does, the layers and how work flows, see the [fleet guide](https://github.com/ferraroroberto/fleet-config/blob/main/docs/fleet-guide.md).

## How it works

An architecture decision record (ADR) here is one GitHub issue in this repo labelled `adr`, written as Context / Decision / Consequences / Status. The issue holds the full reasoning; this page holds the decision in force, in a sentence or two, with its why and a link to the issue.

- **When one is offered:** only a decision that passes all [three tests](owner-decisions.md#when-a-decision-is-offered-as-an-adr).
- **Add one:** file the issue with the `adr` label, then add its entry below in the same PR that applies the decision.
- **Supersede one:** file the new `adr` issue, comment on the old one linking the new, close the old one as not planned, and replace the entry here in the same PR. A superseded decision does not stay listed.
- **Keep it present tense:** an entry says what is true now. History lives in the issue and in `git log`.
- **Keep it in sync:** `tests/test_adr_register.py` runs in the gate and fails when an `adr` issue that is not superseded is missing here, listed twice, or when an entry links no issue, several issues, a non-`adr` issue or a superseded one. It reads the committed snapshot `docs/architecture-decisions.issues.json`, so it runs offline; refresh the snapshot in the same PR whenever an `adr` issue is filed or closed:

```
gh issue list --label adr --state all --limit 500 --json number,title,state,stateReason | .venv/Scripts/python.exe -m json.tool --sort-keys - docs/architecture-decisions.issues.json
```

## Decisions in force

### Ratchets are the default way to enforce a convention

A convention that can be checked mechanically is enforced by a baseline-and-ratchet script in the scaffold family, run as its own stage of each app's gate, rather than by a prose rule, a review step or a one-off lint. Every ratchet is built the same way; only its perimeter and scope differ:

- one stdlib script, `scripts/<name>_ratchet.py`, vendored byte-for-byte into adopters and declared in `[vendored]`;
- a `[<name>_ratchet]` table in `.fleet.toml` (`enabled`, `baseline`, scope options);
- a committed `.ratchets/<name>.json`: `--update-baseline` only shrinks it, `--allow-additions` adds and shows in review;
- exit 0 pass, 1 a measure rose, 2 bad config, 3 not confirmed (fails the gate, never a skip);
- its own stage in `verify-before-ship`, never path-routed;
- a `docs/<name>-ratchet.md` explaining the rule and how to fix a hit;
- a legitimate single exception carries `<rule>-exempt: <reason>`.

A new convention arrives as a ratchet PR here, then `/propagate-vendored`; adopters go in green on an `--init` baseline and burn it down. A one-off lint, hook or checklist item needs a stated reason it cannot be a ratchet. A rule that cannot be checked mechanically stays prose and says why.

Why: prose rules and review steps drift, while a ratchet is deterministic, baselines existing debt instead of blocking on it, and fails the ship the moment a measure rises.

Enforcement: a convention that is one pattern joins the [conventions ratchet](conventions-ratchet.md) as an opt-in rule, even when it reads text files rather than Python (`no-pwsh-stub` refuses the 0-byte `pwsh` stub run as a command in `.md`, `.ps1`, `.bat`, `.toml`, `.yml` and `.py` files; `subprocess-timeout` refuses a blocking `subprocess` call with no `timeout=`); one that needs its own perimeter, baseline semantics or size measure becomes a new ratchet. A convention that gives a job one home (a pooled HTTP session, one connection dependency, one static-file class) is a `[[conventions_ratchet.must_use]]` entry in the adopting repo's `.fleet.toml`: the `must-use` rule fails a call to the primitive made outside the declared helper, so a new single-home helper needs a data entry, not new code in the scaffold. A name a repo removes (a flag, a skill, an environment variable, a config key) is a `retired` entry in the [doc references ratchet](doc-refs-ratchet.md), added in the PR that removes it, so the name cannot return in prose.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/560

### A new test earns its place, and the suite's cost only shrinks

The unit of a test suite's value is the whole unit: a check function or a test file (a pytest module), never one assertion. Every gate run appends one row per unit (outcome, seconds, process spawns, tree hash) to a run ledger kept as machine-local state beside the repo's runtime logs, never committed. One ratchet, `test_value_ratchet`, reads it with several deterministic rules, each its own failure mode: a unit new in the diff shows red-before-fix, a covered line no other unit covers, or a `test-value-exempt: <reason>` marker (`new-test-value`); no unit's spawn count rises (`spawn-budget`); open flakes only shrink in number and age (`flake-ledger`); a unit green in the checkout is green in a fresh clone (`hermetic`, weekly). Burn and load proofs, the full coverage map, the fresh-clone re-run and wall-clock medians never run per change: they run once a week as their own scheduled burst on the main machine. Wall-clock time is measured there and never fails a change. Existing units are baselined and are never failed or deleted for low value; merge candidates go to a person.

Why: suites only grow and their cost lands on every change of every lane; the process spawn count is a cost proxy that does not flake under box load, and a capped flake ledger stops red-then-green reruns from becoming normal, while deleting tests on coverage alone would lose fault detection.

Enforcement: the [test value ratchet](test-value-ratchet.md) and its siblings (`unit_ledger`, `spawn_probe`, `unit_ledger_pytest`, `weekly_burst`), each a vendored component that is off until a repo enables `[test_value_ratchet]` and `[test_value_burst]`; a stale coverage map or a run with no report is exit 3, never a pass.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/858

### Tests read host identity only through a synthetic fixture

A test never reads the machine's account name, home folder or interpreter path. Unit tests take the vendored `synthetic_host` fixture, which provides a fake account, a fake home under `tmp_path` and a fake interpreter path. The e2e harness boots the app under test with `synthetic_host_env()`, and the screenshot privacy check fails a page that shows the synthetic account name as well as one that shows the real home. The synthetic home covers only fixture users and that app process, never the whole gate. `sys.executable` stays the way tests spawn children.

Why: on the developer's machine the real value is the expected one, so a host-reading test passes there and fails first on another host (the macOS nightly), a day late and one repo at a time.

Enforcement: the [conventions ratchet](conventions-ratchet.md)'s test-only `host-identity` rule flags direct reads (`getpass.getuser()`, `os.getlogin()`, `pwd`, `Path.home()`, `~` expansion, account and home variables read through `os.environ`/`os.getenv`). A deliberate privacy check or live-install guard carries `# host-identity-exempt: <reason>`.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/912

### Every UX control is tracked in usage-log

Every feature that touches the UX is tracked in the app's `usage-log` and ingested by its `/api/usage` routes: each interactive control carries a constant tracking id, each sheet, dialog and drawer records its view on open and returns to the previous view on close, and every fleet web app initialises `usage-log` and mounts its routes. Ids are constants, never built from content.

Why: the owner judges UX from usage statistics and time-spent figures, and untracked controls or views make both wrong.

Enforcement: the [usage track ratchet](usage-track-ratchet.md) fails the ship on a new untracked control, an untracked `<dialog>`, a tracking id built at run time, or a web app that does not vendor, start and mount its usage log; existing gaps sit in each app's baseline and only shrink. The client records a `data-track-view` sheet on open and hands back the view on close, and `tests/usage_log/test_usage_log_time_spent.py` holds the time-spent minutes exact through the real client and server.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/561

### Every web app keeps a UX surface map held to its `data-surface` ids

Every fleet web app keeps one [UX surface map](ux-surface-map.md) as a structured YAML file, `docs/ux-surfaces.yaml`: one entry per surface (screen, drill-in, menu, sheet, dialog, popover, Settings row, state, gesture, key) under a stable id, with the links between surfaces. A vendored generator renders the readable `docs/ux-surface-map.md` from it, with one diagram per area; the page is never edited by hand. The map is read by a strict, stdlib-only YAML subset, so the vendored ratchet adds no dependency to any adopter. Each surface root carries the same id as a constant `data-surface="<id>"`, in the e2e capture hook's name form, and the entry and the attribute change in the same PR as the surface.

Why: a layout change or a design review can only check every surface when there is a complete list of them, and a list kept by memory drifts; tying it to the code makes it stay true. One structured source keeps the prose and the diagrams from drifting apart, lets an agent read an entry without parsing paragraphs, and keeps each area's diagram small enough to read.

Enforcement: the [UX surface ratchet](ux-surface-ratchet.md) fails the ship on a surface root with no id, an id with no entry, an entry no element carries, a duplicated id, a link to no entry, or a page not regenerated from the map; existing gaps sit in each app's baseline and only shrink. The design-review and e2e walk reports a surface it opened that carries no id.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/838

### Polling web apps keep a request budget

Every fleet web app that polls its own API holds to a [request budget](polling-budget.md), so it stays responsive on a slower computer with several sessions open: polls are self-scheduling and single-flight (the vendored `poll` helper), a hidden tab makes no requests and returns with one catch-up read, unchanged files cost a stat, work runs in bounded pools by class, fleet-wide scans are capped and run only while viewed, and every request reports `queue_ms`/`worker_ms`/`total_ms` through the vendored request-timing middleware. Every limit (poll intervals, pool sizes, scan TTLs, concurrency caps) is an owner setting in the app's Settings with sensible defaults, never a constant only code can change.

Why: on a slower computer one app reached 10–37 s per request with 17+ in flight, from repeated directory walks, re-parses of unchanged files, overlapping browser polls and one shared thread pool. The same shapes exist in other fleet apps; a faster computer hides the waste rather than removing it.

Enforcement: the [request budget ratchet](request-budget-ratchet.md) fails the ship on a new fixed-rate fetch poll, a poll under the 2 s floor, an undeclared fast server loop, a directory walk in a request handler, a submit to the shared default pool, or a web app without the timing middleware; existing gaps sit in each repo's baseline and only shrink. In the browser tests, the vendored request-budget probe counts requests for a minute visible and a minute hidden on a fake clock.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/914

### Fleet web apps use inset list sections, swipe on inset rows and one Filters & sort sheet

Fleet web apps lay lists out as **inset** sections (rounded cards inside the page gutter) on phone and desktop; a full-bleed list section is not used.

- **Swipe stays.** Left and right swipe actions on list rows are allowed inside inset cards; the reveal clips to the card's rounded corners, and swipe never requires full-bleed.
- **One filter sheet.** A view with two or more filters, sorts or view toggles shows one filter field that opens a single **Filters & sort** sheet holding all of them. The field shows a badge with the number of active filters, so filtered-out content never disappears silently.
- **Settings group labels are sentence case** at the section-header size (16px, weight 700, muted), never all caps; the `overline` wording is retired for them.

Why: the real problem was inconsistency, with some apps and screens full-bleed and others inset. A full-bleed trial on a disposable instance, checked on a phone after every round, did not converge on something clearly better, and inset is what most apps already use, so it is the smaller change. The trial also showed that swipe does not depend on full-bleed and that one filter sheet makes a busy view cleaner.

Enforcement: prose in the design spec (`design.md` / `design.dark.md`, owned by `fleet-config`), applied app by app; no ratchet yet, because the rules are visual and need a rendered check.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/847

### LLM access goes through the local-llm-hub

Downstream apps reach Claude, Gemini and open-weight models through the hub's Anthropic-shape and OpenAI-shape endpoints on `127.0.0.1:8000`, and audio through its transcription and translation endpoints, using standard SDKs. No app wraps `claude -p`, `codex exec` or `gemini -p` itself or hard-codes a whisper port; when the hub lacks a feature, the answer is a plan for the hub to add it.

Why: the hub owns subprocess management, prompt assembly, multi-turn flattening, host routing and observability, and a whisper port is a host-local detail that may not listen on this machine.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/567

### Every repo declares its map card in `.fleet.toml`

Every fleet repo carries a root `.fleet.toml` with its architecture-map card (`layer`, `icon`, `description`, and optional `display_name`, `port`, `chips`, `tag`), and updates it in the same PR as any material change to its port, layer, role, description or exposed services. The system map aggregates these files; the central file is only a fallback.

Why: a central hand-kept list goes stale and fights the rule that conventions flow up, while a card beside the code is updated by the people changing it and a new repo appears on the map with no central edit.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/568

### Plans live as GitHub issues, never as files

Plans, roadmaps and proposed features are GitHub issues, one per topic and self-contained enough to hand off cold; `docs/` holds durable present-tense reference only, with topic filenames and no plans, TODOs or dated retrospectives. The issue, the closing PR and `git log` are the changelog.

Why: files in the tree go stale and pile up, while an issue can be assigned, tracked, superseded and closed.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/569

### Model tiers come from one doc

Lane and sub-agent models are chosen by tier (`easy`, `hard`, `extreme`) and resolved to a model and effort per host from fleet-config's `docs/model-tiers.md`, the single source; skills reference it rather than restating a table. A tier's human-review requirement holds whichever model handles it.

Why: hard-coded model names do not survive a new model or host, while one table changes in one place.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/570

### CI is advisory; the local gate is the contract

A repo's local gate (`scripts/verify-before-ship.ps1`, or `pytest + ruff + mypy`) decides whether a change ships; GitHub Actions is advisory. Each project declares a `## CI expectations` block in its `CLAUDE.md`, and the finish flow skips the CI wait when no declared e2e surface is touched and the local gate is green, reruns only the documented flaky leg and only once, never reruns a real failure, and always states its CI decision.

Why: fleet repos have no branch protection and CI's only signal beyond the local gate is the browser e2e leg, the part that wedges on the hosted runner, so a blocking wait mostly bought delay.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/635

### A clean pull plus restart is the whole update

Updating any fleet app on any machine is exactly a clean `git pull --ff-only` followed by the repo's own restart recipe; no machine ever edits a tracked file to run an app. Ports, hosts, paths and per-machine toggles live only in an ignored `config/*.json` (or `.env`) with a tracked `*.sample` default, and code, scripts and `.bat` files read them through the repo's config resolver. Nothing is signed or re-pointed in place: a machine that needs signed scripts gets them from an ignored, regenerated copy, and repo PowerShell scripts start through the AllSigned-safe launcher pattern. Starting, restarting and gating a repo leaves `git status` unchanged, with runtime output in ignored state dirs, and two instances of one app on a machine differ only in their ignored config.

Why: a machine running a second launcher beside another under AllSigned needed its ports and signatures edited into tracked files, so every update meant discarding local edits before the pull and re-applying them after, the opposite of an app that can be exported to another machine.

Enforcement: the [port host ratchet](port-host-ratchet.md) fails a new port or machine-local host literal in scripts and code outside the declared config resolvers and the samples. The [clean tree ratchet](clean-tree-ratchet.md) is the second: it runs the repo's declared start smoke in the gate on a free port and a scratch data dir, and fails when `git status --porcelain` shows a path the run wrote. The lite family adopts both first, then every other repo through the scaffold.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/891

### Every app installs, reinstalls and migrates through the scaffold installer

Every fleet app that has an install vendors the scaffold [installer](installer.md) and runs all three from it: `setup.bat` for a fresh install, `setup.bat -MigrateFrom <folder>` into a fresh clone, and `setup.bat -Replace` (run from a fresh clone, so an install of any age qualifies; `-InPlace` from an install new enough to have it), the reinstall into the same folder path that keeps the replaced copy as `<folder>.bak-YYYYMMDD-N` until the owner deletes it. What moves is declared in `.fleet.toml` (`[install.endpoint]`, `[install.migrate]` with `copy`, `secrets`, `shared`), never as a machine path. Each app keeps one playbook, `docs/install.md`, with Install, Update and Migrate sections, the Migrate section being only the installer call plus the steps only the owner can take. Updating in place stays the clean pull plus restart above; this decision covers reinstalling from scratch.

Why: moving the toolbox to another PC meant each app improvising its own steps (finding the old copy, copying files by hand, stopping the old process, checking which copy serves the port, repointing the launcher at suffixed folders); one installer that stops only the old folder's processes, keeps a working backup and proves the new clone serves its own commit makes a migration one repeatable call, and the unchanged path means the launcher's settings never need editing.

Enforcement: the [install standard ratchet](install-standard-ratchet.md) fails an adopter's gate when an installer module is missing, undeclared or not at the scaffold's current content, when `[install.migrate]` does not parse, or when the playbook lacks one of the three sections. The playbook template, `docs/templates/install-playbook.md`, carries the three sections, and the scaffold holds it to the same rule.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/1014

### Runtime data lives on a fast drive

A long-lived process resolves its SQLite and other fsync-heavy state through the vendored `src/runtime_data.py`: `runtime_db_path(app, filename, env_var=...)` returns `<root>/<app>/<filename>`, the root being `FLEET_DATA_ROOT` or a fixed per-OS default. A repo-relative database path is a defect, fixed by changing the path and never by a junction; a harness that spawns the app sets `<APP>_DATA_DIR` to a per-run temp folder.

Why: a path relative to the checkout ties the physical drive to wherever the repo was cloned, and a junction records nothing, cannot be tested and is walked by a recursive delete.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/636

### One `get_db` dependency owns each SQLite connection

A FastAPI app backed by SQLite opens connections in one `get_db()` dependency (row factory, WAL, `try`/`finally` close), and handlers take it through `Depends(get_db)`, never calling `sqlite3.connect(...)` themselves. Stdlib `sqlite3` stays the default: no ORM, async driver or pool.

Why: a connection opened per handler leaks when the handler raises, and its setup drifts between handlers.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/637

### Outbound HTTP goes through pooled sessions

A long-lived process makes outbound HTTP calls through the vendored `src/pooled_http.py`, a keep-alive session built once, with one retry only for idempotent methods; a bare `requests.get`/`requests.post` in a poll loop, health check or fan-out is a defect. Failing targets are backed off, fan-out is capped and spawned children are not leaked.

Why: a fresh connection per call leaves a `TIME_WAIT` port behind each time, and on Windows that drains the dynamic port range and takes every local web app down at once.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/638

### A dispatched agent works in a worktree, never the primary checkout

Every agent spawned by fan-out tooling builds in an isolated sibling worktree (`<repo>-wt-<N>`, the primary's `.venv` junctioned in) for every repo, enforced by the claim helper on a flag or a dispatch marker rather than by prose; interactive human sessions keep claim-or-worktree. Teardown is each lane's terminal step and strips the `.venv` junction first, residue halts the run, and a live-e2e guard refusal is a hard stop.

Why: a live webapp or tray served from the primary checkout publishes no claim, so a claim-based rule would let an unattended agent edit files out from under it.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/639

### Console subprocess spawns pass `CREATE_NO_WINDOW`

Every console-tool spawn from a Windows process without its own console passes `creationflags=subprocess.CREATE_NO_WINDOW` (0 off Windows) through one helper, `src/no_window.py`, and never adds `DETACHED_PROCESS`; vendor-verbatim modules derive the flag locally. Keeping a child alive across a tray teardown is done by re-parenting, not by a flag.

Why: each unsuppressed child flashes a console window, and `DETACHED_PROCESS` was measured to show one anyway and not to escape a subtree kill.

Enforcement: the [conventions ratchet](conventions-ratchet.md)'s `no-window` rule.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/640

### The Mac Mini nightly is the fleet's one CI

Each public repo's `main` is checked nightly on the Mac Mini self-hosted runner (`nightly-mac.yml`): unit with `windows_only` tests excluded, WebKit e2e and an iOS Simulator smoke, for every adopter whose `main` moved since its last green night and for every adopter on Sunday. Opt-in is a `[ci.nightly]` table in the repo's `.fleet.toml` plus one line in `.github/nightly-adopters.txt`. A failed test is retried once; a pass on the retry is recorded as flaky, a second failure is red. The local gate stays the per-change contract, hosted Actions gates are retired per repo after three consecutive green nights, and the runner's safety rules (schedule and dispatch only, read-only, no secrets, results stay on the Mac, pull-only delivery) stay as they are. Private repos keep their hosted CI until a private runner registration is decided.

Why: one engine, one result format and no hosted minutes for the whole fleet, running only where something changed, with flakes counted rather than hidden.

Enforcement: `tests/ci/test_nightly_mac_workflow.py` (the safety rules) and `scripts/ci/nightly_matrix.py` (the table contract, selection and retry); contract in [mac-runner.md](mac-runner.md).

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/661
