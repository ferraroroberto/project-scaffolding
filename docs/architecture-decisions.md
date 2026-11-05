# Architecture decisions

The register of every standing architecture decision in the fleet. Read it before building: if a decision here covers what you are about to do, follow it. For a human-readable tour of what each app does, the layers and how work flows, see the [fleet guide](https://github.com/ferraroroberto/fleet-config/blob/main/docs/fleet-guide.md).

## How it works

An architecture decision record (ADR) here is one GitHub issue in this repo labelled `adr`, written as Context / Decision / Consequences / Status. The issue holds the full reasoning; this page holds the decision in force, in a sentence or two, with its why and a link to the issue.

- **Add one:** file the issue with the `adr` label, then add its entry below in the same PR that applies the decision.
- **Supersede one:** file the new `adr` issue, comment on the old one linking the new, close the old one, and replace the entry here in the same PR. A superseded decision does not stay listed.
- **Keep it present tense:** an entry says what is true now. History lives in the issue and in `git log`.

## Decisions in force

### Ratchets are the default way to enforce a convention

A convention that can be checked mechanically is enforced by a baseline-and-ratchet script in the scaffold family, run as its own stage of each app's gate, rather than by a prose rule, a review step or a one-off lint. Every ratchet is built the same way; only its perimeter and scope differ:

- one stdlib script, `scripts/<name>_ratchet.py`, vendored byte-for-byte into adopters and declared in `[vendored]`;
- a `[<name>_ratchet]` table in `.fleet.toml` (`enabled`, `baseline`, scope options);
- a committed `.<name>-ratchet-baseline.json`: `--update-baseline` only shrinks it, `--allow-additions` adds and shows in review;
- exit 0 pass, 1 a measure rose, 2 bad config, 3 not confirmed (fails the gate, never a skip);
- its own stage in `verify-before-ship`, never path-routed;
- a `docs/<name>-ratchet.md` explaining the rule and how to fix a hit;
- a legitimate single exception carries `<rule>-exempt: <reason>`.

A new convention arrives as a ratchet PR here, then `/propagate-vendored`; adopters go in green on an `--init` baseline and burn it down. A one-off lint, hook or checklist item needs a stated reason it cannot be a ratchet. A rule that cannot be checked mechanically stays prose and says why.

Why: prose rules and review steps drift, while a ratchet is deterministic, baselines existing debt instead of blocking on it, and fails the ship the moment a measure rises.

Enforcement: a convention that is one pattern joins the [conventions ratchet](conventions-ratchet.md) as an opt-in rule, even when it reads text files rather than Python (`no-pwsh-stub` refuses the 0-byte `pwsh` stub run as a command in `.md`, `.ps1`, `.bat`, `.toml`, `.yml` and `.py` files; `subprocess-timeout` refuses a blocking `subprocess` call with no `timeout=`); one that needs its own perimeter, baseline semantics or size measure becomes a new ratchet. A convention that gives a job one home (a pooled HTTP session, one connection dependency, one static-file class) is a `[[conventions_ratchet.must_use]]` entry in the adopting repo's `.fleet.toml`: the `must-use` rule fails a call to the primitive made outside the declared helper, so a new single-home helper needs a data entry, not new code in the scaffold. A name a repo removes (a flag, a skill, an environment variable, a config key) is a `retired` entry in the [doc references ratchet](doc-refs-ratchet.md), added in the PR that removes it, so the name cannot return in prose.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/560

### Every UX control is tracked in usage-log

Every feature that touches the UX is tracked in the app's `usage-log` and ingested by its `/api/usage` routes: each interactive control carries a constant tracking id, each sheet, dialog and drawer records its view on open and returns to the previous view on close, and every fleet web app initialises `usage-log` and mounts its routes. Ids are constants, never built from content.

Why: the owner judges UX from usage statistics and time-spent figures, and untracked controls or views make both wrong.

Enforcement: the [usage track ratchet](usage-track-ratchet.md) fails the ship on a new untracked control, an untracked `<dialog>`, a tracking id built at run time, or a web app that does not vendor, start and mount its usage log; existing gaps sit in each app's baseline and only shrink. The client records a `data-track-view` sheet on open and hands back the view on close, and `tests/usage_log/test_usage_log_time_spent.py` holds the time-spent minutes exact through the real client and server.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/561

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
