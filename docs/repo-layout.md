# Repo layout

Where code goes in a fleet repo. Every repo has one **shape**, declared as `shape` in its `.fleet.toml`; this page gives each shape a canonical tree, a placement rule for new code, and the extra roots it allows. The structure ratchet (`scripts/structure_ratchet.py`) points its failure messages at the section anchors below, so the headings are stable: rename one only together with the ratchet.

Shape ids (the exact `.fleet.toml` `shape` values): [`webapp-tray`](#webapp-tray), [`streamlit`](#streamlit), [`pipeline-cli`](#pipeline-cli), [`skills-governance`](#skills-governance), [`node`](#node), [`static-site`](#static-site), [`agent-workspace`](#agent-workspace), [`service`](#service).

## Rules for every shape

Five rules hold in every shape. The structure ratchet enforces the first four; the fifth is a convention. Existing offenders are baselined and may not grow; a new offender fails the gate. It also holds the root folders to the shape's tree, with no baseline (see the end of this page).

### File size

*Enforced.* A file over **1,000 lines** does not grow. New code goes in a new module beside it, named for what it does. Applies to code, stylesheets, markup and tests alike.

### Function length

*Enforced.* A Python or JS function over **100 lines** does not grow. Split it into named helpers, in the same module or a new one beside it. A nested function counts inside its outer function, so a view's `mount<View>()` closure is held as a whole: its helpers move out of the closure into the view's folder. Tests get the same limit.

### Flat directory

*Enforced.* A directory past **40 modules** (its own `.py`, `.js`, `.mjs` and `.css` files, `__init__.py` aside) takes no new module. New code goes in a domain subpackage (`src/<domain>/`, `tests/unit/<domain>/`), which is the only path once a directory is full.

### Layer contract

*Enforced.* **`src/` never imports `app/`.** UI calls logic, never the reverse. A helper both need lives in `src/`.

### Test mirror

*Documented.* Tests mirror what they test: `tests/unit/<domain>/` mirrors `src/<domain>/`, an `api/` folder under `tests/` mirrors the routers. A repo still on flat `tests/` names files `test_<module>.py` and mirrors into subfolders once it nears 40 test modules.

## webapp-tray

A FastAPI + static PWA app owned by a Windows tray.

```
launcher.py  tray.bat  webapp.bat  setup.bat
app/
  cli/                      argparse dispatcher only
  tray/                     tray.py + vendored single_instance.py, watchdog.py
  webapp/
    server.py               app factory, mounts routers and static
    manager.py              spawn and lifecycle of the uvicorn process
    middleware.py           auth, cache headers
    event_loop.py           pinned selector-loop factory
    routers/<concern>.py    thin: parse, call src, return
    static/
      index.html  manifest.webmanifest  icons/
      styles/base.css       tokens + shell
      styles/<view>.css     one per view
      js/<view>/index.js    mount<View>() + its helpers
      js/shared/            used by two or more views
      _vendored/            vendor-verbatim components
src/
  <domain>/                 one subpackage per domain
  config.py  no_window.py  build_info.py
scripts/                    ops CLIs, never imported by app/
assets/                     static files the app reads or ships: logos, icons, fixtures
config/                     tracked config files and samples, never secrets
tests/
  unit/<domain>/            mirrors src/
  api/                      TestClient, mirrors routers/
  js/                       JS unit tests
  e2e/                      Playwright
docs/layout.md
```

Where new code goes:

- New endpoint: `app/webapp/routers/<concern>.py`, holding request parsing and the response only. The logic goes in `src/<domain>/`.
- New view: `static/js/<view>/` and `static/styles/<view>.css`, both linked from `index.html`. Never a new block in a shared stylesheet or another view's script.
- New logic module: a `src/<domain>/` package. Flat `src/` is fine until it reaches 40 modules.
- New ops script: `scripts/`. A helper the app imports belongs in `src/`.

Allowed extra roots: `data/` (runtime input and output, gitignored contents), `brand/` (icon masters). Anything else is declared.

## streamlit

A Streamlit app with Python pipelines.

```
launch_app.bat
app/
  app.py                    st.set_page_config + st.navigation only
  views/<name>.py           one render() per view
  styles/                   CSS overlays
src/                        no streamlit import (ruff TID251)
  <domain>/                 once src/ passes 40 modules
  pipelines/<job>.py        one run() per job
scripts/
tests/                      test_<module>.py, mirrors src/
  e2e/                      Playwright, if any
docs/layout.md
```

Where new code goes:

- New page: `app/views/<name>.py` exposing `render()`, registered in `app/app.py`. Never `tab_<name>.py`, `<name>_tab.py` or a `main()` entry point. The folder is `views/`, not `pages/`, because Streamlit auto-discovers `pages/`. The rest of the view rules are in [Streamlit conventions](streamlit-conventions.md).
- New logic: `src/`. A view that grows past 100 lines of logic hands that logic to `src/`.
- New batch job: `src/pipelines/<job>.py` exposing `run()`, callable from a view, the CLI and tests.

Allowed extra roots: `data/`, `brand/`.

## pipeline-cli

A command-line tool or batch job with no UI. Two variants.

### Single tool

```
src/<pkg>/
  __main__.py | cli.py      the one entry point
  <domain>/                 one subpackage per domain
tests/                      top level, mirrors <pkg>
scripts/                    one-off tools
config/*.example            real config is gitignored
main.py                     optional thin wrapper for scheduled jobs
docs/layout.md
```

### Multi-tool repo

```
<tool>/                     one root package per tool
common/                     shared by two or more tools
tests/<tool>/               never co-located with the tool
scripts/
docs/layout.md              lists every tool in one line
```

Where new code goes:

- A new command is a subcommand of the one entry point, never another root `main_<name>.py`. A scheduled job that calls a script by path keeps a thin wrapper at that path.
- In a multi-tool repo, a new tool gets a new root package and a line in `docs/layout.md`. Code a second tool needs moves to `common/`.

Allowed extra roots: `data/`, and in a multi-tool repo each declared tool package.

## skills-governance

Agent skills, hooks and the fleet's governance tooling.

```
skills/<name>/SKILL.md
skills/<name>/*.py          private to that one skill
skills/_lib/<entry>.py      CLIs invoked by path: they keep their path
skills/_lib/<pkg>/          library code shared by two or more skills
hooks/                      one module per hook + hooks/_lib/
scripts/
tests/<area>/               hooks/, skills/, acceptance/
docs/layout.md
```

Where new code goes:

- A helper used by one skill stays in that skill's folder. At its second caller it moves to `skills/_lib/`.
- An entry script that a `SKILL.md` invokes by path keeps that path. Its body may move into `skills/_lib/<pkg>/` behind it.

Allowed extra roots: `architecture/` (generated maps).

## node

A Node.js project.

```
src/<area>/
test/                       Node's own convention, accepted as is
scripts/
package.json                its "verify" script is the gate
docs/layout.md
```

Where new code goes: a new module goes in `src/<area>/`; its test goes in `test/`, mirroring `src/`.

Allowed extra roots: none beyond the tree.

## static-site

Hand-written HTML, CSS and JS with no build step.

```
index.html  <page>.html
css/
js/
assets/
games/<name>.html           one self-contained page each, where used
docs/layout.md
```

Where new code goes: a new page is a root `<page>.html` (or `games/<name>.html` for a self-contained game); its styles and scripts go in `css/` and `js/`, never inline beyond a few lines.

Allowed extra roots: none beyond the tree.

## agent-workspace

A repo an agent works in rather than code it ships: instructions, and skills under the agent's hidden folder, plus the gate's scripts. Tests live beside the code they test.

```
CLAUDE.md  AGENTS.md         instructions; AGENTS.md points at CLAUDE.md
.claude/skills/<name>/       one folder per skill, loaded by the repo's own sessions
.claude/skills/_shared/      code shared by two or more skills
scripts/                     the gate and its checks
docs/layout.md
```

Where new code goes:

- A new skill is a new `.claude/skills/<name>/` folder; its helpers and tests stay in that folder.
- Sessions load a skill by its path, so a skill folder keeps its path. Code a second skill needs moves to `.claude/skills/_shared/`.

Allowed extra roots: none beyond the tree. No folder is required: hidden folders are always allowed, and `scripts/` is optional.

## service

A long-lived local service: the service itself in `src/`, the admin web app it mounts in `app_web/`, and the Windows tray that owns it.

```
src/                        the service: server, routing, backends
app_web/                    the admin web app the service mounts
  routers/  static/
tray/                       the tray that starts and watches the service
launchers/                  per-platform start scripts (.bat and .sh)
config/                     checked-in config and *.example files
scripts/
tests/                      top level
docs/layout.md
```

Where new code goes: service logic goes in `src/`, an admin page or endpoint in `app_web/`, tray behaviour in `tray/`. `src/` mounts `app_web/`, so this shape sets no layer pair.

Allowed extra roots: `assets/`. A repo that ships per-platform deploy trees (`linux/`, `mac/`, `docker/`) declares each in `extra_roots`.

## Every repo's `docs/layout.md`

Each repo carries a `docs/layout.md`: its own annotated tree, one line per top-level folder and per subpackage, saying what lives there. It ends with the repo's declared exceptions, each with its reason. The README links it in one index line.

```
app/                 Streamlit UI: entry point and views
src/billing/         invoice parsing and totals
src/pipelines/       one run() per batch job
data/                runtime input and output (contents gitignored)

Exceptions
custom_components/   required at the root by Home Assistant
```

A justified exception (a root a framework requires, a vendored tool) is declared once, in `docs/layout.md` and in `.fleet.toml` `extra_roots`, never improvised. `docs/`, `.github/` and hidden folders are allowed in every shape; any other root not in the shape's tree, its allowed extra roots or `extra_roots` fails the structure ratchet's root-layout check.

## Migration

New code follows the tree from the day this page lands. Existing code moves only when its own split issue comes up: no big-bang moves. Until then the ratchet's baseline holds existing files and directories at their current size.

## This scaffold's own tree

The scaffold is a `streamlit` repo and conforms to that section. It also publishes the web-app and tray components every `webapp-tray` repo vendors, so it carries these declared exceptions. This section stands in for its `docs/layout.md`.

- `app/tray/` and `app/webapp/static/_vendored/`: component sources for `webapp-tray` adopters, with no tray or server of their own.
- `app/log_panel.py`: the live log panel the views render, kept beside `app.py`.
- `tray.bat.template` and `launch_server.{bat,sh}`: copy-to-adapt launchers.
- `src/` is flat (under 40 modules) with two domain packages, `src/notify/` and `src/doc_capture/`.
- `scripts/verify_skill_templates/`: templates for `scripts/gen_verify_skill.py`.
