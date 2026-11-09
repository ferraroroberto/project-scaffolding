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

One sign is a hint; two or more on the same concept is a suspect worth a deep-dive.

## Finding them: two passes

1. **Deterministic scan.** A cheap, repeatable pass over the code flags suspects from the signs above: lifecycle-named booleans assigned in more than one module, a concept name appearing in several guards with different conditions, status strings compared by equality in many places. It runs often and never decides anything; its output is a ranked list of suspects, not a verdict. No scan script exists in the scaffold yet; until one does, the agent pass below does the searching by hand.
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
