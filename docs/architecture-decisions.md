# Architecture decisions

The register of every standing architecture decision in the fleet. Read it before building: if a decision here covers what you are about to do, follow it.

## How it works

An architecture decision record (ADR) here is one GitHub issue in this repo labelled `adr`, written as Context / Decision / Consequences / Status. The issue holds the full reasoning; this page holds the decision in force, in a sentence or two, with its why and a link to the issue.

- **Add one:** file the issue with the `adr` label, then add its entry below in the same PR that applies the decision.
- **Supersede one:** file the new `adr` issue, comment on the old one linking the new, close the old one, and replace the entry here in the same PR. A superseded decision does not stay listed.
- **Keep it present tense:** an entry says what is true now. History lives in the issue and in `git log`.

## Decisions in force

### Ratchets are the default way to enforce a convention

A convention that can be checked mechanically is enforced by a baseline-and-ratchet script in the scaffold family, run as its own stage of each app's gate, rather than by a prose rule, a review step or a one-off lint. Every ratchet is built the same way (one stdlib script, a `.fleet.toml` table, a committed baseline, exit 3 for not confirmed); a rule that cannot be checked mechanically stays prose and says why.

Why: prose rules and review steps drift, while a ratchet is deterministic, baselines existing debt instead of blocking on it, and fails the ship the moment a measure rises.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/560

### Every UX control is tracked in usage-log

Every feature that touches the UX is tracked in the app's `usage-log` and ingested by its `/api/usage` routes: each interactive control carries a constant tracking id, each sheet, dialog and drawer records its view on open and returns to the previous view on close, and every fleet web app initialises `usage-log` and mounts its routes. Ids are constants, never built from content.

Why: the owner judges UX from usage statistics and time-spent figures, and untracked controls or views make both wrong. Enforcement is the usage-tracking ratchet, which lands with https://github.com/ferraroroberto/project-scaffolding/issues/559; until then the decision is followed by convention and not yet checked by the gate.

Issue: https://github.com/ferraroroberto/project-scaffolding/issues/561
