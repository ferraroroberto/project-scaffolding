# Repo layout

Where code goes in a fleet repo. Every repo has one **shape**, declared as `shape` in its `.fleet.toml`; this page gives each shape a canonical tree, a placement rule for new code, and the extra roots it allows. The structure ratchet (`scripts/structure_ratchet.py`) points its failure messages at the section anchors below, so the headings are stable: rename one only together with the ratchet.

Shape ids (the exact `.fleet.toml` `shape` values): [`webapp-tray`](#webapp-tray), [`streamlit`](#streamlit), [`pipeline-cli`](#pipeline-cli), [`skills-governance`](#skills-governance), [`node`](#node), [`static-site`](#static-site), [`agent-workspace`](#agent-workspace), [`service`](#service).

## Rules for every shape

These rules hold in every shape. The structure ratchet enforces all but the test mirror, which is a convention. Existing offenders are baselined and may not grow; a new offender fails the gate. It also holds the root folders to the shape's tree: an undeclared one fails with no baseline, and a declared extra root is baselined and shrink-only (see the end of this page). Each shape's section opens with its contract table: root folders, root files, folder types and homes, so the expected layout of any repo can be read from that table.

### File size

*Enforced.* A file over **1,000 lines** does not grow. New code goes in a new module beside it, named for what it does. Applies to code, stylesheets, markup and tests alike. A split aims for about 750 lines: the count of files at 900–1,000 lines may not rise either ([near-limit band](structure-ratchet.md#near-limit-band)).

### Function length

*Enforced.* A Python or JS function over **100 lines** does not grow. Split it into named helpers, in the same module or a new one beside it. A nested function counts inside its outer function, so a view's `mount<View>()` closure is held as a whole: its helpers move out of the closure into the view's folder. Tests get the same limit. Helpers aim for about 75 lines: the count of functions at 90–100 lines may not rise either.

### Flat directory

*Enforced.* A directory past **40 modules** (its own `.py`, `.js`, `.mjs` and `.css` files, `__init__.py` aside) takes no new module. New code goes in a domain subpackage (`src/<domain>/`, `tests/unit/<domain>/`), which is the only path once a directory is full.

### Layer contract

*Enforced.* **`src/` never imports `app/`.** UI calls logic, never the reverse. A helper both need lives in `src/`.

### Extra roots

*Enforced, shrink-only.* A root folder the shape's tree does not list goes in `extra_roots` in `.fleet.toml`, with its reason in `docs/layout.md`. The ratchet records every such folder in the baseline (`root_extras`) and fails on one that is not recorded, so the list can only go down. Before declaring one, check the three outcomes: the folder holds code that belongs under `src/` or `app/`, so move it; more than one repo of the shape needs it, so it joins the shape's allowed set (as `webapp/` did for `webapp-tray`); or it is required where it is (a framework loads it by name), so it is declared with its reason and recorded with `--update-baseline --allow-additions`.

Every exception is a to-do, not a permission. **An `extra_roots` or `extra_root_files` entry the preset already allows fails as redundant**: delete it from `.fleet.toml`. A folder or file several repos of one shape share is promoted into that shape's preset; one repo's quirk stays a recorded exception until it moves.

### Root files

*Enforced, shrink-only.* A file directly at the root is one the common set or the shape's contract table lists, as a name or a glob. Anything else (a loose script, a second README, a one-off launcher) goes into a folder the shape lists: `scripts/` for a tool, `docs/` for a document, `config/` for a sample. A root file a repo must keep (a framework reads it there, a scheduled job calls it by path) is declared in `extra_root_files` in `.fleet.toml` with its reason in a comment beside it, and is recorded in the baseline like an extra root.

A config template (`*.example.*`, `*.sample.*`, `*.json.example`) is the committed copy of a gitignored machine-local file the app reads from the root, so it sits beside that file; the `webapp-tray` and `streamlit` presets list the forms their repos use.

| Common root files (every shape) |
|---|
| `README.md`, `CLAUDE.md`, `AGENTS.md`, `LICENSE`, `.fleet.toml`, `.gitignore`, `.gitattributes`, `.ignore`, `.env.example`, `.*-baseline.json`, `requirements*.txt`, `pyproject.toml`, `pytest.ini`, `package*.json` |

### Folder types

*Enforced, shrink-only.* A typed folder takes files of its type only, so a script cannot sit in `docs/`, a notebook in `src/` or a binary in `tests/`. The longest typed folder holding a file sets its type, so `tests/fixtures/` and `tests/e2e/fixtures/` (the pages an e2e suite serves) take any type over `tests/` (code), and `tests/e2e/shots/` (the screenshot baselines the vendored `shot_baseline` writes) takes images. A folder no row names is untyped: `data/`, `assets/`, `brand/`, `content/` and `site/` take anything. Everywhere, a file named `README.md`, and any path with a hidden segment (`.gitkeep`, `app/.streamlit/`), is allowed. Extensions compare lowercased.

| Type | Extensions |
|---|---|
| `code` | `.py`, `.pyi`, `.js`, `.mjs`, `.cjs`, `.ts`, `.sql` |
| `code+shell` | `code` plus `.ps1`, `.psm1`, `.sh`, `.bat`, `.cmd` |
| `shell` | `.ps1`, `.psm1`, `.sh`, `.bat`, `.cmd` |
| `config` | `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.example`, `.sample` |
| `doc` | `.md`, `.mmd`, `.html`, `.json` and images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.ico`) |
| `web` | `code`, the images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.ico`), `.html`, `.css`, `.json`, `.webmanifest`, `.woff`, `.woff2`, `.ttf`, `.otf`, `.txt`, `.license` |
| `image` | `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.ico` |
| `css` | `.css` |
| `js` | `.js`, `.mjs` |
| `tooling` | `code+shell`, `config`, `.md`, `.html`, `.txt` |
| `patch` | `.patch` |
| `any` | anything |

| Common folder types (every shape) |
|---|
| `docs/` `doc`, `scripts/` `code+shell`, `src/` `code`, `tests/` `code+shell`, `tests/fixtures/` `any`, `tests/e2e/shots/` `image`, `tests/e2e/fixtures/` `any`, `config/` `config` |

### Second-level placement

*Enforced where a shape declares homes, shrink-only.* Under a home root a file lives in one of the shape's homes, so a web app's routers, static assets and domain code cannot scatter. The ratchet counts the files outside every home per folder and fails when a folder is new or holds more than its baseline. Existing outliers are baselined. A shape declares homes only where its repos agree; each shape's contract table lists them, or says why it has none.

### Test mirror

*Documented.* Tests mirror what they test: `tests/unit/<domain>/` mirrors `src/<domain>/`, an `api/` folder under `tests/` mirrors the routers. A repo still on flat `tests/` names files `test_<module>.py` and mirrors into subfolders once it nears 40 test modules.

## webapp-tray

A FastAPI + static PWA app owned by a Windows tray.

| Contract | |
|---|---|
| Root folders | required `app`, `src`, `tests`, `docs`; also `scripts`, `data`, `brand`, `assets`, `config`, `webapp` |
| Root files | the common set, plus `tray.bat`, `webapp.bat`, `launcher.py`, `setup.bat`, `webapp_tunnel_named.bat`, `start.bat`, `launch_app.bat`, `*.example.*`, `*.sample.*` |
| Folder types | the common set, plus `app/` `code`, `app/webapp/` `web` |
| Homes | `app/*.py`, `app/cli/`, `app/tray/`, `app/webapp/*.py`, `app/webapp/routers/`, `app/webapp/static/`, `src/`, and a surface package `app/webapp/<package>/` |

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
- New second HTTP surface (a separately bound listener, for example a public player tunnelled on its own port): `app/webapp/<package>/` with its own `server.py`, static files and entry point. It mounts nothing from the main app and the main app mounts nothing from it, so the package boundary is the isolation boundary. Any other new folder under `app/webapp/` is still misplaced.
- New ops script: `scripts/`. A helper the app imports belongs in `src/`.

Homes (the [second-level placement](#second-level-placement) contract); a file anywhere else under `app/` fails, for example a new templates folder or a helpers module:

```
app/*.py                    shell modules directly in app/
app/cli/  app/tray/         everything below
app/webapp/*.py             factory, manager, middleware
app/webapp/routers/         everything below
app/webapp/static/          everything below
app/webapp/<package>/       a surface package: any folder here that holds its own server.py, everything below it
src/                        any module or domain subpackage
```

Allowed extra roots: `data/` (runtime input and output, gitignored contents), `brand/` (icon masters), `webapp/` (the app's runtime files: tunnel and launcher config, not code). Anything else is declared.

## streamlit

A Streamlit app with Python pipelines.

| Contract | |
|---|---|
| Root folders | required `app`, `src`, `tests`; also `scripts`, `data`, `brand`, `config` |
| Root files | the common set, plus `launch_app.bat`, `launch_app.sh`, `launch_server.bat`, `launch_server.sh`, `*.example.*`, `*.json.example`, `tray.bat.template` |
| Folder types | the common set, plus `app/` `code`, `app/styles/` `css` |
| Homes | `app/*.py`, `app/views/`, `app/styles/`, `app/.streamlit/` |

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

Allowed extra roots: `data/`, `brand/`, `config/`.

## pipeline-cli

A command-line tool or batch job with no UI. Two variants.

| Contract | |
|---|---|
| Root folders | required `tests`; also `src`, `common`, `tools`, `scripts`, `config`, `data` |
| Root files | the common set, plus `main.py`, `launch_*.bat` |
| Folder types | the common set, plus `common/` `code` |
| Homes | none: a single tool keeps one package under src/, a multi-tool repo keeps one package per tool under tools/, so no second-level rule fits both |

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
tools/<tool>/               one package per tool, any file type: code, launchers, Markdown, HTML, images, samples
common/                     shared by two or more tools
tests/<tool>/               never co-located with the tool
scripts/
docs/layout.md              lists every tool in one line
```

Where new code goes:

- A new command is a subcommand of the one entry point, never another root `main_<name>.py`. A scheduled job that calls a script by path keeps a thin wrapper at that path.
- In a multi-tool repo, a new tool gets a new `tools/<tool>/` package and a line in `docs/layout.md`. `src/` stays code-only, so a tool folder that holds more than code never goes there. Code a second tool needs moves to `common/`.

Allowed extra roots: `data/`. A multi-tool repo needs none for its tools.

## skills-governance

Agent skills, hooks and the fleet's governance tooling.

| Contract | |
|---|---|
| Root folders | required `skills`, `tests`; also `hooks`, `scripts`, `architecture` |
| Root files | the common set, plus `install.ps1` |
| Folder types | the common set, plus `skills/` `tooling`, `hooks/` `tooling` |
| Homes | `skills/*/` |

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

| Contract | |
|---|---|
| Root folders | required `src`; also `test`, `scripts`, `patches` |
| Root files | the common set |
| Folder types | the common set, plus `test/` `code`, `patches/` `patch` |
| Homes | none: the one adopter keeps a flat src/, unlike the src/<area>/ tree below, so nothing is shared yet |

```
src/<area>/
test/                       Node's own convention, accepted as is
scripts/
patches/                    dependency patches (`patch-package` writes `.patch` files here)
package.json                its "verify" script is the gate
docs/layout.md
```

Where new code goes: a new module goes in `src/<area>/`; its test goes in `test/`, mirroring `src/`.

Allowed extra roots: none beyond the tree.

## static-site

Hand-written HTML, CSS and JS with no build step.

| Contract | |
|---|---|
| Root folders | required none; also `css`, `js`, `assets`, `games`, `content`, `site`, `scripts`, `tests` |
| Root files | the common set, plus `*.html` |
| Folder types | the common set, plus `css/` `css`, `js/` `js` |
| Homes | none: one adopter is hand-written at the root and the other is built from content/, so they share no second level |

```
index.html  <page>.html
css/
js/
assets/
games/<name>.html           one self-contained page each, where used
tests/                      where the site has tests: functions, end-to-end flows, link and build checks
docs/layout.md
```

Where new code goes: a new page is a root `<page>.html` (or `games/<name>.html` for a self-contained game); its styles and scripts go in `css/` and `js/`, never inline beyond a few lines. A test goes in `tests/`, grouped by what it tests.

**A built static site** is the same shape with a build step that runs locally, never on the host. The source lives in `content/`, the build writes the publish folder `site/`, which is committed so the host serves it as-is, and `scripts/` holds the build, the preview server and the gate:

```
content/                    the source: pages, partials, images, static/ (stylesheet, script)
  static/_vendored/         the fleet web-page components, copied verbatim
site/                       the build output the host publishes; never edited by hand
scripts/
  build.py                  content/ -> site/; the gate fails when the committed site/ differs
  site_images.py            vendored: WebP variants per image role, the social-card JPEG
  site_routes.py            vendored: the host's URL rules
  site_serve.py             vendored: preview server with the host's URL rules
  site_check.py             vendored: offline routes, hosts and local-reference check
  verify-before-ship.ps1
docs/layout.md
```

Where new code goes in a built site: a new page is a file in `content/`; its styles go in the site's own stylesheet beside the vendored components (`app/site/static/_vendored/README.md` in this scaffold, the load order and what stays the site's own); a build step goes in `scripts/`. Never edit `site/` by hand: rebuild it.

Allowed extra roots: none beyond the tree; `content`, `site` and `scripts` need no `extra_roots`.

## agent-workspace

A repo an agent works in rather than code it ships: instructions, and skills under the agent's hidden folder, plus the gate's scripts. Tests live beside the code they test.

| Contract | |
|---|---|
| Root folders | required none; also `scripts` |
| Root files | the common set |
| Folder types | the common set |
| Homes | none: its code lives under .claude/, a hidden folder the layout never checks |

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

| Contract | |
|---|---|
| Root folders | required `src`, `tests`, `app_web`, `tray`; also `scripts`, `config`, `launchers`, `assets` |
| Root files | the common set, plus `tray.bat`, `run_*.bat`, `run_*.sh` |
| Folder types | the common set, plus `app_web/` `web`, `tray/` `code+shell`, `launchers/` `shell` |
| Homes | `app_web/*.py`, `app_web/routers/`, `app_web/static/`, `tray/*.py` |

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

A justified exception (a root a framework requires, a vendored tool) is declared once, in `docs/layout.md` and in `.fleet.toml` `extra_roots`, never improvised. `docs/`, `.github/` and hidden folders are allowed in every shape; any other root not in the shape's tree, its allowed extra roots or `extra_roots` fails the structure ratchet's root-layout check. A declared exception is recorded in the ratchet's baseline and can only leave it.

## Migration

New code follows the tree from the day this page lands. Existing code moves only when its own split issue comes up: no big-bang moves. Until then the ratchet's baseline holds existing files and directories at their current size.

## This scaffold's own tree

The scaffold is a `streamlit` repo and conforms to that section. It also publishes the web-app and tray components every `webapp-tray` repo vendors, so it carries these declared exceptions. This section stands in for its `docs/layout.md`.

- `app/tray/`, `app/webapp/serve.py` and `app/webapp/static/_vendored/`: component sources for `webapp-tray` adopters, with no tray or server of their own.
- `app/log_panel.py`: the live log panel the views render, kept beside `app.py`.
- `tray.bat.template` and `launch_server.{bat,sh}`: copy-to-adapt launchers. The `streamlit` preset lists `tray.bat.template`, because every repo cloned from the scaffold starts with it at the root.
- The component sources under `app/` (`app/site/`, `app/tray/`, `app/webapp/`) are catalogued in `[components]`, so placement and folder types skip them: each lives at its adopters' path, where that tree holds the copy. Each `_vendored/` channel folder is skipped whole, so its readme and the gallery page (`demo.html` and its scripts) beside the components are skipped too. `app/tray/` and `app/webapp/` are namespace packages, with no `__init__.py` of their own.
- `src/` is flat (under 40 modules) with two domain packages, `src/notify/` and `src/doc_capture/`.
- `scripts/tools/verify_skill_templates.py`: the templates `scripts/tools/gen_verify_skill.py` renders, as string constants, so the folder takes code only.
