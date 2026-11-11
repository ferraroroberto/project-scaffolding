# Implicit state machines: how to spot and declare them

An *implicit state machine* is a concept that really has modes (stopped, loading, ready, failed) but never declares them as one official state. The modes are inferred from scattered flags, empty fields, status strings, timers and process handles, so the legal combinations live only in someone's head. This page is the fleet convention for recognising one, confirming it, and replacing it with a declared state.

## Why it matters

Every reader of the scattered facts re-derives the mode on its own, and two readers disagree. Typical failures:

- one screen shows a loading item as idle while another shows it as running;
- a crash during startup reappears as "stopped", so the reason is lost;
- a failed probe reads as a negative answer ("port is free", "nothing is running") instead of "could not tell";
- an impossible combination (finished and in progress, ready with no process) passes silently because nothing says it is impossible.

A declared state turns each of these into a loud, local failure: a dead process with a live load record is `failed` with a reason, never `stopped`, and a newcomer reads the whole lifecycle from one module.

## The signs

An area is a suspect when it shows one or more of these:

- **Lifecycle-named flags no type owns.** `loading`, `ready`, `started`, `pending`, `connected`, `dirty` as separate booleans or nullable fields, set in different places.
- **Guards that differ per screen or route.** The same concept is tested as `if proc and not err` in one handler and `if port_open` in another.
- **One concept's variables spread across modules**, each read on its own, with no function that combines them.
- **Flags that outlive their trigger.** A `busy` or `retrying` flag set on entry and cleared only on the happy path, so an exception leaves it stuck.
- **Outcomes passed as prose.** A result carried as a free-text message or an exception string that a caller later matches with `in` or a regex to decide what to do.
- **Unknown folded into a negative.** A timeout, a stale cache or an unresolved probe stored as `False`, `None` or an empty list, indistinguishable from a real "no".
- **In-memory restart latches.** A "fired", "sent" or "armed" fact kept only in a long-lived process's memory, so a restart forgets it and the action repeats (or never happens). No scan sees this; it is a review question for every long-lived process: what does this latch read after a restart?

One sign is a hint; two or more on the same concept is a suspect worth a deep-dive.

## Finding them: two passes

1. **Deterministic scan.** A cheap, repeatable pass over the code flags suspects from the signs above. It is three opt-in rules of the [conventions ratchet](conventions-ratchet.md): `state-literal` (a lifecycle string compared or stored as a status), `state-set-repeat` (one set of states spelled in two modules) and `state-write` (one lifecycle flag written from two modules). It reads Python and JavaScript/TypeScript, so a web app's frontend state is scanned with its backend, and a frontend that re-spells its backend's states is a suspect too. It runs in the gate on every change and never decides anything; its output is a list of suspects, not a verdict. It cannot see a state held in names that say nothing, a mode inferred from an empty field or a timer, or an in-memory restart latch: those stay signs for the agent pass.
2. **Agent deep-dive.** An agent takes each suspect and confirms it against the code and the live behaviour before anything is declared. For each machine it records:
   - the variables that together hold the state, and where each is written and read;
   - the **reachable states** (combinations that actually occur) against the **declared states** (what the code or UI names today);
   - the **impossible combinations** the current code permits;
   - the transitions and what triggers each;
   - the readers, and how each one infers the mode now.

   A suspect that turns out to be a plain flag with no lifecycle is dropped. Machines are ranked by pain (user-visible disagreement, lost failure reasons, bugs that recur), and the first fix is the low-risk one: a single machine, readers migrated one at a time.

## The target shape

- **One declared state type.** An enum or tagged union naming every state, each with a one-line meaning. The set is closed: adding a mode means adding a state and handling it everywhere.
- **One derive function.** A pure function that takes one observation (process alive, probe answered, port snapshot, exit code, timestamps) and returns the state. It is the only code that maps facts to a mode.
- **Every reader calls it.** UI chips, API routes, health summaries and actions read the derived state. A new reader never re-derives a mode from the underlying handle, port or probe; a review that sees one doing so sends it back.
- **`unknown` is its own state.** When the facts needed to tell two states apart could not be gathered, the result is `unknown` with a reason, never folded into the nearest negative. Actions that depend on the answer stay disabled for it.
- **Failures carry a reason.** A `failed` state records why (died on its own, missed a deadline, stopped answering), so the reader shows the cause instead of a generic stopped.
- **Transitions leave a record.** Where "died on its own" must be told from "stopped on purpose", the start path writes a record and a deliberate stop clears it; the derive function reads it.
- **Compatibility is derived too.** Older fields kept for older clients are computed from the same observation, not maintained separately.
- **Tests are a table.** One test row per reachable observation and its expected state, including the impossible combinations and the `unknown` cases.

## Worked example

local-llm-hub declares the per-model serving state: `stopped`, `loading`, `ready`, `adopted`, `failed` and `unknown`, derived in one module from one observation and read the same way by the Models tab, the audio health route and the fleet placement summary. Its write-up, [local-llm-hub `docs/serving-state.md`](https://github.com/ferraroroberto/local-llm-hub/blob/main/docs/serving-state.md), is the model to follow: why the machine was implicit, the state table, who reads it, and the rule that a new reader calls the derive path.

## Vibe coding recreates them

Without a guardrail, each quick change adds one more flag or one more local guard, because that is the smallest diff that fixes the symptom in front of it. Over a few rounds a lifecycle appears that nobody designed. The guardrails are structural, not advisory:

- the derivation lives in one function and readers are expected to call it, so the cheapest change is to extend the state, not to add a flag;
- a new lifecycle-named flag in a diff is a review question: which declared state does this belong to?
- when a fix needs a fact the state does not carry, the fact joins the observation and the derive function, not a reader.

## Declaring one: checklist

1. Name the concept and list the variables that hold its state today.
2. List reachable and impossible combinations from the code and live behaviour.
3. Pick the state names; include `failed` with reasons and `unknown` where a probe can fail.
4. Write the derive function and its table test.
5. Migrate the readers one at a time, deleting each re-derivation as it moves.
6. Document the machine in the repo's own `docs/<concept>-state.md`: why it is declared, the state table, who reads it.
7. Declare it in the repo's `.fleet.toml` as a `[[state_machines]]` table (`name`, `module`, `type`, optional `derive`; the module may be Python or JS/TS; see [conventions-ratchet.md](conventions-ratchet.md)), so the state rules stop reporting its module and keep reporting any other module that re-derives it. Shrink the conventions baseline with `--update-baseline`.
8. Prove the machine refuses an illegal transition: at least one test carries the `state-machine-proof: <name>` marker (see the scoreboard below).

## Scoreboard: is the fleet ending in a better state?

`scripts/tools/state_scoreboard.py` answers that with numbers read from committed state only, so the same command at the same commit prints the same bytes and a "before" taken now is comparable with an "after" taken later. It lives in this scaffold and is not vendored: it reads the adopters from outside and writes to none of them.

```
scripts/tools/state_scoreboard.py --at default          # each repo's shipped tip (origin/HEAD)
scripts/tools/state_scoreboard.py --at 2026-11-01       # the state at the start of that day (UTC), per repo
scripts/tools/state_scoreboard.py --at default --json   # the same, as data
```

Run it with the scaffold's `.venv` interpreter. `--at` takes a date (UTC; resolved on each repo's default branch), any revision, `default` (each repo's `origin/HEAD` tip: use it for "today", because a checkout that is behind or on a feature branch would otherwise be what gets measured) or nothing (each repo's checked-out `HEAD`). `--root` names the folder holding the repos (default: the fleet root), `--repo` limits the run. The fleet is every git checkout there with a committed `.fleet.toml`.

| Metric | What it counts | Target |
|---|---|---|
| Findings | The `state-literal`, `state-set-repeat` and `state-write` counts in each repo's committed conventions baseline, split `py` / `js` (a baseline key that is not a `.py` file counts as `js`). The baseline is the ceiling on today's hits: the ratchet fails any rise and a fixed hit only shrinks it | 0 |
| Declared machines | The `[[state_machines]]` entries and their owner modules, each with its declared state count: a Python owner's class members and `Literal` strings, a JavaScript/TypeScript owner's `enum`, `class`, object, array or string-literal union, read with the conventions ratchet's own tokenizer | up, as suspects are confirmed |
| Transition proof | Per machine, the test functions carrying a `state-machine-proof: <machine name>` marker. A machine with 0 is flagged `no proof` | at least 1 per machine |
| Duplicate derivations | `state-write` plus `state-set-repeat`: places outside any declared owner that write a lifecycle flag the owner also writes or re-spell the owner's set of states | 0 |
| Bug signal | With `--bug-split <date>`: closed `bug` issues that name a machine (its name, its type, or two of its states), before vs after the date. Reads GitHub through `gh` | none: lagging and noisy, read it as a trend |

**The proof marker.** A test proves a machine refuses an illegal transition by carrying `state-machine-proof: <name>` in the comment block right above its `def`, in its docstring or in a comment in its body, where `<name>` is the machine's `name` in `[[state_machines]]`. Only functions named `test*` in a test file (under a `tests/` or `test/` folder, or named `test_*.py` / `*_test.py`) count; a marker in production code counts for nothing. In JavaScript and TypeScript the marker is a comment (a marker inside a string counts for nothing) in the block right above a `test(...)` or `it(...)` call, or inside that call, in a file under a `tests/` or `test/` folder or named `*.test.*` / `*.spec.*`; a file the tokenizer cannot read makes the machine's proof count unknown, never 0. The marker is a claim the reviewer checks: the scoreboard counts tests, it does not run them.

**What each cell can say.** A number is measured; `?` means the repo (or that section) could not be read (no committed baseline, a `.fleet.toml` or baseline that does not parse, a test module that does not parse, a failed git or `gh` call) and is never folded into zero; `-` means the repo has not opted into a state rule, so there is nothing to measure. A date before a repo's first commit reports the repo as `absent`. The fleet totals sum only the measured repos and print how many that was, so a total of 0 over three repos cannot be mistaken for a clean fleet. The exit code is 0 when everything readable was read and 3 (not confirmed) when any repo is unknown.

Only counts and file paths are printed: no issue text and no code.
