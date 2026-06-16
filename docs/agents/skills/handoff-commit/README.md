# handoff-commit — canonical home moved

The full skill (`SKILL.md`) **no longer lives here.** Its canonical home is `fleet-config`:

> `ferraroroberto/fleet-config` → `skills/handoff-commit/SKILL.md`

`handoff-commit` is a **machine-wide** skill — it sits *above* all projects and is installed once into `~/.claude/skills/` (reaching Codex via `~/.agents/skills/`) by `fleet-config`, the singleton machine config. Per the boundary rule (`project-scaffolding` owns what goes *inside* a project; `fleet-config` owns what sits *above* all projects), it belongs to `fleet-config`, **not** to this clone-per-project scaffold.

It used to be duplicated here verbatim, which had already started to drift. The copy was replaced with this pointer so there is a single source of truth.

- **To use it:** it's already installed on the machine via `fleet-config`. Run `/handoff-commit [<commit-ish>]`.
- **To change it:** edit the canonical `SKILL.md` in `fleet-config`. Do **not** re-add a fork here.
