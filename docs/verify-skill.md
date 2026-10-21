# Project verify skill (`gen_verify_skill.py`)

The scaffold generates a web app's own `verify-<app>` skill instead of asking each project to hand-write one. It is written for an agent that has never seen the app: how to launch it from an empty data directory, check its health, drive each feature in a real browser, record evidence, clean up, and keep the feature map true to the source. (`project-scaffolding#412`; the shape follows the "create / maintain a verification skill" pattern.)

`CLAUDE.md` keeps the one-line rules; this file is the full procedure, the `[verify]` schema, and the limits.

## What it generates

Into `.claude/skills/verify-<app>/` of the adopter (or any `--out` directory):

```text
SKILL.md                 frontmatter + Launch, Doctor, Drive, Evidence, Cleanup, Maintain, Gotchas
features/README.md       index: one row per view -> file, sub-feature count, driving-node count, seed sources
features/<view>.md       one per view: how a user reaches it, sub-features, the pytest node that drives each, Gotchas
```

The name is `verify-<app>`, not `verify`, so it never collides with another scope's skill under the portable-skills contract (`docs/agents/project-skills.md`).

| Section | What the agent gets |
| --- | --- |
| Launch | Reach a usable state from an **empty** data dir: scratch folder, the `data_dir_env` pointed at it, the repo's own disposable boot, the refuse-an-occupied-port rule, the live opt-in it must never set, "ready means `GET <ready_path>` is 200", never touch the tray. |
| Doctor | Read-only checks, each `ok` / `stale` / `unknown`, never folded: venv, a real browser launch, the disposable port, and the live app's `/api/version` `git_sha` against `HEAD` (a loopback GET, nothing restarted). |
| Drive | The feature table and one pytest command that runs every mapped node. A node that cannot run is a blocked drive, not a skipped one. |
| Evidence | Screenshots and traces go to the scratchpad, never the tree. A PR gets the node list, the pass output and one build line (`git_sha`, `built_at`), no images. |
| Cleanup | Close every browser, stop only the instance this run booted by its recorded PID and port, never kill by image name, remove the scratch folder, confirm the port is free. |
| Maintain | The two-half re-check below. |

## Where the map comes from

Nothing is hand-written. The generator reads, statically (`ast` and `tomllib`; nothing of the adopter is imported or run, no browser), in this order:

1. **`surface(page, "<view>.<surface>")` calls** in `tests/e2e/**/*.py` (the vendored hook, `tests/e2e/_surface.py`). The prefix before the first dot is the view, each name is a sub-feature, and the enclosing test function is the driving pytest node (`file::func` or `file::Class::func`). `surface(page, "a" if x else "b")` maps both names. Two tests that open the same surface both appear.
2. **`[[design.review.extra_steps]]`** in `.fleet.toml` (`tab`, `id`, `click`): how a user reaches a view that is not a tab. A step whose `id` matches a view adds a "From the `<tab>` tab, click `<selector>`" line; an unmatched one becomes a view of its own.
3. **The `## UX surface` key views** in `CLAUDE.md`: a route per view. A route no `surface()` name covers still gets a feature file (`/` is `home`), with "no test drives this view yet" in its Drive line rather than an invented node.

`[[e2e.surface]]` is listed in `features/README.md` as context only. Those tables are diff-routing groups (path to pytest targets), not a feature list, and most apps do not declare any.

Why not the design-review inventory: it is a local, uncommitted report built from the same `surface()` names, so a generator cannot depend on it. The committed call sites are the deterministic source behind it.

A `surface()` call the parse cannot turn into a node (a name that is not a string literal, or a call in a helper that is not a test function) is **listed under "Not mapped"** in `features/README.md` and printed as a warning. It is never silently dropped, so the map cannot look complete when it is not.

## The `[verify]` table

The launch recipe is per-project prose in `CLAUDE.md` today; maintain mode needs it machine-readable. Declare it in the adopter's `.fleet.toml`:

```toml
[verify]
boot           = "tests/e2e/conftest.py::boot_instance"   # a callable the e2e suite boots, or an argv list
live_optin_env = "FS_E2E_LIVE"                            # the opt-in Launch must never set
ready_path     = "/healthz"                               # default
data_dir_env   = "FS_DATA_DIR"                            # default: <APP>_DATA_DIR, via app_dir_env_var()
```

`boot` and `live_optin_env` are required. A missing key (or a missing table) is written into `SKILL.md` as a visible `FILL:` line and is **never guessed**; `--check` reports `blocked` until it is filled. The schema is owned by `fleet-config` (`architecture/README.md`), tracked by a pointer issue there.

## Generate and adopt

1. Add `[verify]` to the adopter's `.fleet.toml`.
2. From the scaffold checkout: `& .\.venv\Scripts\python.exe scripts\gen_verify_skill.py --repo <adopter>`. The default output is `<adopter>\.claude\skills\verify-<app>`; `--out <dir>` writes the skill directory elsewhere (use your scratchpad to try it first). `--app` overrides the slug (default: the folder name, minus a `-wt-N` suffix).
3. Apply the `.gitignore` allowlist the run prints (the generator never edits `.gitignore`; the rule text is the one in `docs/agents/project-skills.md`).
4. Fill the `## Gotchas` of the views you drive; that is the only hand-written part.
5. Execute Launch, Doctor, Drive, Evidence, Cleanup once and record the node list, the pass output and the build line in the PR. A skill that was never executed has not been delivered.
6. Add the per-skill discovery link for the clients you use, per `docs/agents/project-skills.md`.

**Idempotent.** Generated text sits between `<!-- gen:begin NAME -->` and `<!-- gen:end NAME -->` markers. A rewrite replaces only those blocks; the frontmatter, `## Gotchas` and anything else outside the markers is yours and survives, and two runs on one tree are byte-identical. A block the template gains later is inserted before `## Gotchas`. A view that lost its seed is left in place (never deleted) and reported by `--check`. Unpaired markers stop the run (exit 2).

**Not vendored.** The output is a per-project instance, not byte-identical bytes, so `gen_verify_skill.py` is not a `[components]` entry. Adopters run it from the scaffold checkout.

## Maintain mode

The generated skill's `## Maintain` section is the procedure; `--check` is the mechanism. It has two halves:

```text
gen_verify_skill.py --repo <adopter> --check
    -> STATIC=clean|changed|blocked                      exit 0 / 1 / 2

gen_verify_skill.py --repo <adopter> --check --live-url <base url> --junit <pytest junit xml>
    -> STATIC=...  then  MAINTAIN=clean|changed|blocked  exit 0 / 1 / 2
```

- **Static half.** Fresh seeds against the committed skill. It names new `surface()` names not in the map, mapped names whose test or call is gone, driving nodes that moved, and any other generated block that differs (a changed selector shows up as the view's block changing).
- **Live half.** Launch a disposable instance, run every mapped node with `--junitxml`, clean up, then pass the instance's base URL and the XML. The generator probes `GET <ready_path>` and reads the XML for every mapped node (all parametrized variants).
- `--live-url` and `--junit` go together, and only with `--check`. A `MAINTAIN` verdict without both would be a guess, so it is not produced.

| Outcome | Meaning |
| --- | --- |
| `clean` | The map matches the source **and** the instance answered 200 **and** every mapped node passed. |
| `changed` | The map is stale. Fix it in one PR that touches only the skill's files: regenerate, review the diff, fill gotchas. Never edit a test, delete a journey or loosen a selector to make a drive pass. |
| `blocked` | An unreachable app, a ready path that does not answer 200, a mapped node that failed, errored, was skipped or is missing from the XML, an unreadable XML, a `[verify]` placeholder, no generated skill, or no mapped nodes at all. A red node is a possible regression for a human to decide on, not map drift. |

Worst wins (blocked over changed over clean). Unknown is never `clean`.

## Limits

- **Static parse only.** A `surface()` name built at runtime, or a call made from a helper the test delegates to, is listed as not mapped. The hook's own rule applies: call `surface(` directly in the test body.
- **Key views are parsed from `CLAUDE.md`.** Only bullets under `- key views:` inside the first `## UX surface` section, each starting with a route (`/...`).
- **A view with no `surface()` name has no driving node.** The file says so; it does not invent one.
- **The live probe is one `GET`.** It proves the recipe reaches a serving instance, not that a journey works; the mapped nodes prove journeys. The probe skips certificate verification for an `https` URL because it targets a disposable loopback instance.
- **Doctor's live comparison can read `stale` after a squash-merge** while the content is identical; the skill says to diff the content before concluding the wrong code is live.
- **PowerShell snippets** in the generated skill are written for Windows (the fleet's host); the Python in them is portable.
- Streamlit POC spikes are out of scope, as is replacing the e2e suite: the skill drives the suite's own nodes.
