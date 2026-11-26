# Owner decisions: grill rounds and scored proposal reports

Two fleet conventions for putting choices to the owner. One covers a piece of work that needs several decisions settled before it starts, the other a report that proposes changes. The shared references and code live in `fleet-config`; this page states the rules every repo follows and points there for the mechanics.

## Grill rounds

Applies to any skill or session that has to settle several owner decisions before it acts. The shared format is `fleet-config`'s [interview rounds](https://github.com/ferraroroberto/fleet-config/blob/main/docs/skills/interview-rounds.md) reference: link it, never restate its template in a skill.

- **Facts are looked up, never asked.** The owner gets only decisions: choices that the code, the docs and the issue history cannot settle. A lookup that fails is reported as unknown, with the reason, and does not become a question.
- **Numbered questions, each with a recommended answer.** The recommendation is the agent's real pick, grounded in what it found, and phrased so a plain "yes" accepts it. Answers by number override only the numbers given.
- **Rounds until nothing is open.** A round asks every decision whose prerequisites are settled; a dependent decision waits for a later round. An answer that reopens a settled decision reopens what depends on it.
- **One final OK, and silence decides nothing.** The result is shown before anything is acted on. With no human present, the interview stops and nothing is filed or changed.

[`/issue-grill`](https://github.com/ferraroroberto/fleet-config/blob/main/docs/skills/issue-grill.md) applies the format to filing a large or fuzzy idea as an issue. The [design issue](https://github.com/ferraroroberto/fleet-config/issues/2263) holds the reasoning.

### When a decision is offered as an ADR

A decision is offered as an `adr` issue for the [architecture decision register](architecture-decisions.md) when all three hold:

1. it is hard to reverse;
2. it would surprise a reader who lacks the context;
3. it came out of a real trade-off.

It is offered, not filed: the owner approves it. A decision that misses any of the three stays in the issue that made it.

## Scored proposal reports

Applies to any report that proposes changes: retro findings, improvement ideas, audit suggestions. The standard is `fleet-config`'s [proposal reports](https://github.com/ferraroroberto/fleet-config/blob/main/docs/proposal-reports.md), which owns the input schema, the commands and the quadrant boundaries. Use its renderer rather than building a page by hand. The [design issue](https://github.com/ferraroroberto/fleet-config/issues/2261) holds the reasoning.

- **One standard page.** Every suggestion is scored 1-5 for impact and for effort, plotted on an impact-versus-effort quadrant and listed with filters (repo, category, quadrant). The page is self-contained and readable on a phone.
- **One Board question per suggestion.** Each links to its own row on the page and offers accept, decline or later, so every suggestion is decided on its own. Running the report again does not repeat a question.
- **The report acts on nothing.** No issue is filed and nothing is built until a suggestion is accepted; an accepted one then goes through `/issue-add` like any other work.
