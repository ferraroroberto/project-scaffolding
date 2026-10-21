"""Generate a web app's project-local `verify-<app>` skill (project-scaffolding#412).

A skill written for an agent that has never seen the app: Launch (reach a usable
state from an empty data dir), Doctor (read-only health check), Drive (real
selectors, one pytest node per feature), Evidence, Cleanup and Maintain, plus a
feature map: `features/README.md` and one `features/<view>.md` per view.

    python scripts/gen_verify_skill.py --repo <adopter> [--app NAME] [--out DIR]
    python scripts/gen_verify_skill.py --repo <adopter> --check
    python scripts/gen_verify_skill.py --repo <adopter> --check --live-url URL --junit XML

**Seeded from committed inventories, read statically** (`ast` + `tomllib`; no
browser, nothing of the adopter imported or executed), in this order:

  1. `surface(page, "<view>.<surface>")` calls in `tests/e2e/**/*.py` (the #408
     hook): grouped by the view prefix, each name a sub-feature, each enclosing
     test function its driving pytest node.
  2. `[[design.review.extra_steps]]` in `.fleet.toml` (tab, id, click): how a user
     reaches a view that is not a tab.
  3. The `## UX surface` key views in `CLAUDE.md`: routes, and views no
     `surface()` name covers.
  `[[e2e.surface]]` is listed as context only: those are diff-routing groups, not
  a feature list.

**Idempotent.** Generated text sits between `<!-- gen:begin NAME -->` and
`<!-- gen:end NAME -->` markers; a rewrite replaces only those blocks, so the
hand-written `## Gotchas` and anything else outside the markers survives, and two
runs on one tree are byte-identical. A view that lost its seed is left in place
(never deleted) and reported by `--check`.

**`[verify]` in `.fleet.toml`** is the machine-readable launch recipe:

    [verify]
    boot           = "tests/e2e/conftest.py::boot_instance"   # or an argv list
    live_optin_env = "FS_E2E_LIVE"                            # the opt-in Launch must never set
    ready_path     = "/healthz"                               # default
    data_dir_env   = "FS_DATA_DIR"                            # default <APP>_DATA_DIR

A missing key is written as a visible `FILL:` line, never guessed, and `--check`
reports `blocked` until it is filled.

**`--check`** compares fresh seeds with the committed skill. Static half alone ends
`STATIC=clean|changed|blocked` (exit 0 / 1 / 2). With both `--live-url` (the
disposable instance's base URL, probed at `ready_path`) and `--junit` (the pytest
junit XML of the mapped nodes) it also ends `MAINTAIN=clean|changed|blocked`:
`clean` needs a map that matches **and** an answering instance **and** every
mapped node passed. Unreachable, a node that failed, errored, skipped or is
missing from the XML, or a `[verify]` placeholder is `blocked`, never `clean`.
Worst wins: blocked over changed over clean.

Never writes outside `--out`. Never edits `.gitignore`: it prints the narrow
allowlist from `docs/agents/project-skills.md` instead. Not vendored: adopters run
this from the scaffold checkout. Procedure and limits: `docs/verify-skill.md`.
"""

from __future__ import annotations

import argparse
import ast
import logging
import re
import ssl
import sys
import tomllib
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))  # a script's own dir is sys.path[0], not the repo root

from src.runtime_data import app_dir_env_var  # noqa: E402

logger = logging.getLogger("gen_verify_skill")

TEMPLATES = Path(__file__).resolve().parent / "verify_skill_templates"
E2E_DIR = "tests/e2e"
DEFAULT_READY_PATH = "/healthz"
FILL = "FILL:"
STATES = ("clean", "changed", "blocked")  # ordered: a later state wins when combined
EXIT = {"clean": 0, "changed": 1, "blocked": 2}

_BLOCK_RE = re.compile(r"<!-- gen:begin (\w+) -->\n(.*?)\n<!-- gen:end \1 -->", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")
_ROW_RE = re.compile(r"^\| (.+?) \| (.+?) \| (.+?) \|$")


class GeneratorError(Exception):
    """A seed or file the generator cannot establish: fail loud, never guess."""


# --------------------------------------------------------------------- model


@dataclass
class Sub:
    label: str
    surface: str = ""  # the surface() name; empty for a view seeded without one
    nodes: list[str] = field(default_factory=list)


@dataclass
class View:
    slug: str
    subs: list[Sub] = field(default_factory=list)
    reach: list[str] = field(default_factory=list)
    seeds: set[str] = field(default_factory=set)

    @property
    def nodes(self) -> list[str]:
        return sorted({n for s in self.subs for n in s.nodes})


@dataclass
class Model:
    app: str
    views: list[View]
    verify: dict[str, object]
    live_port: str
    browser: str
    e2e_surfaces: list[tuple[str, list[str]]]
    unresolved: list[str]
    fills: list[str]

    @property
    def nodes(self) -> list[str]:
        return sorted({n for v in self.views for n in v.nodes})


# ------------------------------------------------------------------ seed read


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", text.lower()).strip("-")


def default_app(repo: Path) -> str:
    return re.sub(r"-wt-\d+$", "", repo.name)


def read_fleet_toml(repo: Path) -> dict[str, object]:
    path = repo / ".fleet.toml"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GeneratorError(f"{path} not found: every fleet repo declares a .fleet.toml") from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise GeneratorError(f"{path} is unreadable: {exc}") from exc


def _dig(data: object, *keys: str) -> object:
    """`data[k1][k2]...`, or None as soon as a level is not a table or lacks the key."""
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _literal_names(node: ast.expr) -> list[str] | None:
    """The string(s) a `surface()` name argument can take, or None when not literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        body, orelse = _literal_names(node.body), _literal_names(node.orelse)
        if body is not None and orelse is not None:
            return body + orelse
    return None


def _is_surface_call(call: ast.Call) -> bool:
    func = call.func
    return (isinstance(func, ast.Name) and func.id == "surface") or (
        isinstance(func, ast.Attribute) and func.attr == "surface"
    )


def _name_arg(call: ast.Call) -> ast.expr | None:
    if len(call.args) >= 2:
        return call.args[1]
    return next((kw.value for kw in call.keywords if kw.arg == "name"), None)


def collect_surface_sites(repo: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """(surface name, pytest node) pairs plus the call sites that cannot be mapped.

    A call whose name is not a literal, or that sits outside a test function, is
    listed as unresolved rather than dropped: the map must not look complete
    when it is not.
    """
    sites: list[tuple[str, str]] = []
    unresolved: list[str] = []
    e2e = repo / E2E_DIR
    if not e2e.is_dir():
        return sites, unresolved
    for path in sorted(e2e.rglob("*.py")):
        rel = path.relative_to(repo).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            raise GeneratorError(f"{rel} cannot be parsed: {exc}") from exc
        for scope, prefix in _scopes(tree, rel):
            for call in (n for n in ast.walk(scope) if isinstance(n, ast.Call) and _is_surface_call(n)):
                arg = _name_arg(call)
                names = _literal_names(arg) if arg is not None else None
                if names is None:
                    unresolved.append(f"`{prefix}`: a `surface()` name that is not a string literal")
                elif not prefix.split("::")[-1].startswith("test"):
                    unresolved.append(f"`{prefix}`: `{names[0]}` is called outside a test function")
                else:
                    sites.extend((name, prefix) for name in names)
    return sites, sorted(set(unresolved))


def _scopes(tree: ast.Module, rel: str) -> list[tuple[ast.AST, str]]:
    """Each top-level function and class method, with its pytest node id."""
    scopes: list[tuple[ast.AST, str]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            scopes.append((node, f"{rel}::{node.name}"))
        elif isinstance(node, ast.ClassDef):
            scopes.extend(
                (sub, f"{rel}::{node.name}::{sub.name}")
                for sub in node.body
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef)
            )
    return scopes


def parse_key_views(claude_md: str) -> list[tuple[str, str]]:
    """(route, description) from the `## UX surface` block's `- key views:` list."""
    lines = claude_md.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^## UX surface\b", ln)), None)
    if start is None:
        return []
    views: list[tuple[str, str]] = []
    in_views = False
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if re.match(r"^- key views:", line):
            in_views = True
            continue
        if in_views:
            bullet = re.match(r"^\s{2,}-\s+(/\S*)\s*(.*)$", line)
            if bullet:
                views.append((bullet.group(1), bullet.group(2).strip().strip("()").strip()))
            elif re.match(r"^- ", line):
                in_views = False
    return views


def route_slug(route: str) -> str:
    return slugify(route.strip("/").replace("/", "-")) or "home"


def _verify_table(fleet: dict[str, object], app: str) -> tuple[dict[str, object], list[str]]:
    raw = fleet.get("verify")
    table: dict[str, object] = dict(raw) if isinstance(raw, dict) else {}
    fills: list[str] = []
    if not table:
        fills.append("`.fleet.toml` has no `[verify]` table")
    else:
        for key in ("boot", "live_optin_env"):
            if not table.get(key):
                fills.append(f"`[verify]` has no `{key}`")
    table.setdefault("ready_path", DEFAULT_READY_PATH)
    table.setdefault("data_dir_env", app_dir_env_var(app))
    return table, fills


def build_model(repo: Path, app: str) -> Model:
    fleet = read_fleet_toml(repo)
    sites, unresolved = collect_surface_sites(repo)

    views: dict[str, View] = {}

    def view(slug: str) -> View:
        return views.setdefault(slug, View(slug))

    by_name: dict[str, set[str]] = {}
    for name, node in sites:
        by_name.setdefault(name, set()).add(node)
    for name in sorted(by_name):
        prefix, _, rest = name.partition(".")
        v = view(slugify(prefix))
        v.seeds.add("surface()")
        v.subs.append(Sub(label=rest or prefix, surface=name, nodes=sorted(by_name[name])))

    steps = _dig(fleet, "design", "review", "extra_steps")
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict) or not step.get("id"):
            continue
        slug = slugify(str(step["id"]))
        existing = slug in views
        v = view(slug)
        v.seeds.add("extra_steps")
        v.reach.append(f"From the `{step.get('tab', '?')}` tab, click `{step.get('click', '?')}`.")
        if not existing:
            v.subs.append(Sub(label=str(step["id"])))

    claude_md = repo / "CLAUDE.md"
    key_views = parse_key_views(claude_md.read_text(encoding="utf-8")) if claude_md.is_file() else []
    for route, desc in key_views:
        slug = route_slug(route)
        existing = slug in views
        v = view(slug)
        v.seeds.add("key views")
        v.reach.append(f"Open the route `{route}`" + (f" ({desc})." if desc else "."))
        if not existing:
            v.subs.append(Sub(label=desc or route))

    e2e = _dig(fleet, "e2e", "surface")
    e2e_surfaces = [
        (str(s.get("name", "?")), [str(t) for t in s.get("pytest_targets", [])])
        for s in (e2e if isinstance(e2e, list) else [])
        if isinstance(s, dict)
    ]

    verify, fills = _verify_table(fleet, app)
    port = str(fleet.get("port", "")).lstrip(":")
    browsers = _dig(fleet, "e2e", "static_browsers")
    return Model(
        app=app,
        views=sorted(views.values(), key=lambda v: v.slug),
        verify=verify,
        live_port=port if port.isdigit() else "",
        browser=str(browsers[0]) if isinstance(browsers, list) and browsers else "",
        e2e_surfaces=e2e_surfaces,
        unresolved=unresolved,
        fills=fills,
    )


# --------------------------------------------------------------------- render


def fill_template(name: str, values: dict[str, str]) -> str:
    text = (TEMPLATES / name).read_text(encoding="utf-8").replace("\r\n", "\n")

    def sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise GeneratorError(f"template {name} uses unknown placeholder {{{{{key}}}}}")
        return values[key]

    return _PLACEHOLDER_RE.sub(sub, text)


def _bt(items: list[str]) -> str:
    return "<br>".join(f"`{i}`" for i in items) if items else "none: see Drive below"


def pytest_cmd(model: Model, targets: list[str]) -> str:
    browser = f" --browser {model.browser}" if model.browser else ""
    return f".\\.venv\\Scripts\\python.exe -m pytest {' '.join(targets)} -q{browser}"


def _feature_table(view: View) -> str:
    rows = ["| Sub-feature | Surface name | Driving test node(s) |", "| --- | --- | --- |"]
    for sub in view.subs:
        label = sub.label.replace("|", "/")
        rows.append(f"| {label} | {f'`{sub.surface}`' if sub.surface else '-'} | {_bt(sub.nodes)} |")
    return "\n".join(rows)


def render_feature(model: Model, view: View) -> str:
    seed = " · ".join(s for s in ("surface()", "extra_steps", "key views") if s in view.seeds)
    reach = "\n".join(f"- {r}" for r in view.reach) or (
        "- Not declared in `.fleet.toml` or `CLAUDE.md`. Read the driving test: it opens the surface "
        "before it calls `surface()`."
    )
    if view.nodes:
        drive = f"`{pytest_cmd(model, view.nodes)}` (the suite boots its own disposable instance)."
    else:
        drive = (
            "no `surface()` name covers this view yet, so no test drives it. Launch an instance and "
            "reach it as described above; to make it testable, add a test that opens it and calls `surface()`."
        )
    return fill_template(
        "feature.md.tmpl",
        {"view": view.slug, "seed": seed, "reach": reach, "table": _feature_table(view), "drive": drive},
    )


def _index(model: Model) -> tuple[str, str]:
    rows = ["| Feature | Sub-features | Driving nodes | Seeded from |", "| --- | --- | --- | --- |"]
    for v in model.views:
        seeds = " · ".join(s for s in ("surface()", "extra_steps", "key views") if s in v.seeds)
        rows.append(f"| [{v.slug}]({v.slug}.md) | {len(v.subs)} | {len(v.nodes)} | {seeds} |")
    sections: list[str] = []
    if model.e2e_surfaces:
        items = [f"- `{n}`: {', '.join(f'`{t}`' for t in targets) or 'no targets'}" for n, targets in model.e2e_surfaces]
        sections.append("\n".join(["**Declared e2e surfaces** (`[[e2e.surface]]`: diff-routing groups, context only, not seeds):", "", *items]))
    if model.unresolved:
        items = [f"- {u}" for u in model.unresolved]
        sections.append("\n".join(["**Not mapped** (a `surface()` call the generator cannot turn into a driving node):", "", *items]))
    empty = "_No declared e2e surfaces; every `surface()` call was mapped._"
    return "\n".join(rows), "\n\n".join(sections) if sections else empty


def _boot_step(model: Model) -> str:
    boot = model.verify.get("boot")
    if not boot:
        return f"3. **Boot.** {FILL} set `boot` in `.fleet.toml`'s `[verify]` table and regenerate. Until then this skill cannot launch the app."
    if isinstance(boot, list):
        cmd = " ".join(str(c) for c in boot)
        return f"3. **Boot** with the repo's declared command, from the repo root: `{cmd}`. Record the PID and port it prints."
    return (
        f"3. **Boot** with the repo's own disposable instance, `{boot}`: the e2e suite's session fixture calls it, so "
        "the Drive nodes boot one for you. For a standalone instance, read its signature, call it from a throwaway "
        "script in your scratchpad with your scratch folder, and record the PID and port it gives back."
    )


def _optin_step(model: Model) -> str:
    env = model.verify.get("live_optin_env")
    if not env:
        return f"5. **Live opt-in.** {FILL} set `live_optin_env` in `[verify]` and regenerate."
    return (
        f"5. **Never set `{env}`.** That is the opt-in that points the suite at the live app. It stays unset, "
        "and a guard refusal is a hard stop, never something to bypass."
    )


_DOCTOR_LIVE = """ Read-only `GET /api/version` on the live app (`:@PORT@`, loopback), compared with `git rev-parse HEAD`:

```
@'
import json, ssl, subprocess, urllib.request
PORT = @PORT@
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE  # loopback only
state = "unknown"
for scheme in ("https", "http"):
    try:
        with urllib.request.urlopen(f"{scheme}://127.0.0.1:{PORT}/api/version", timeout=3, context=ctx) as r:
            sha = str(json.load(r).get("git_sha") or "")
    except Exception:
        continue
    if sha and head:
        state = "ok" if head.startswith(sha) or sha.startswith(head) else "stale"
    break
print("live_version=" + state)
'@ | & .\\.venv\\Scripts\\python.exe -
```

`ok`: same commit. `stale`: different (a squash-merge can change the sha while the content is identical, so diff the content before concluding the wrong code is live). `unknown`: unreachable or no version endpoint. A stale or unknown live app does not block the disposable run; report it."""


def _doctor_live(model: Model) -> str:
    if not model.live_port:
        return " No live `port` in `.fleet.toml`, so there is nothing to compare: report `unknown`."
    return _DOCTOR_LIVE.replace("@PORT@", model.live_port)


def render_skill(model: Model) -> str:
    port = model.live_port
    table = ["| Feature | File | Sub-features | Driving nodes |", "| --- | --- | --- | --- |"]
    table.extend(f"| {v.slug} | `features/{v.slug}.md` | {len(v.subs)} | {len(v.nodes)} |" for v in model.views)
    files = sorted({n.split("::")[0] for n in model.nodes})
    return fill_template(
        "SKILL.md.tmpl",
        {
            "app": model.app,
            "data_env": str(model.verify["data_dir_env"]),
            "boot_step": _boot_step(model),
            "optin_step": _optin_step(model),
            "live_optin": f"`{model.verify['live_optin_env']}`" if model.verify.get("live_optin_env") else "the live opt-in",
            "live_port_note": f" (`:{port}`)" if port else "",
            "ready_path": str(model.verify["ready_path"]),
            "doctor_live": _doctor_live(model),
            "drive_intro": (
                "One feature file per view, each with the exact pytest node that drives it. Read the file for the "
                "view you are checking, run its Drive command, and look at what it asserts before you trust a pass."
            ),
            "feature_table": "\n".join(table),
            "all_cmd": pytest_cmd(model, files) + " --junitxml <scratch>/maintain.xml" if files else "no mapped nodes yet",
        },
    )


def render_all(model: Model) -> dict[str, str]:
    outputs = {"SKILL.md": render_skill(model)}
    index, context = _index(model)
    outputs["features/README.md"] = fill_template("features_README.md.tmpl", {"app": model.app, "index_table": index, "context": context})
    for v in model.views:
        outputs[f"features/{v.slug}.md"] = render_feature(model, v)
    return outputs


# ---------------------------------------------------------------------- merge


def blocks(text: str) -> dict[str, str]:
    found = {m.group(1): m.group(2) for m in _BLOCK_RE.finditer(text)}
    if text.count("<!-- gen:begin ") != len(found) or text.count("<!-- gen:end ") != len(found):
        raise GeneratorError("a gen:begin / gen:end marker is unpaired or malformed")
    return found


def merge_blocks(existing: str, rendered: str) -> str:
    """Replace each generated block in `existing`; everything outside the markers is kept."""
    fresh = blocks(rendered)
    have = blocks(existing)
    merged = _BLOCK_RE.sub(lambda m: f"<!-- gen:begin {m.group(1)} -->\n{fresh.get(m.group(1), m.group(2))}\n<!-- gen:end {m.group(1)} -->", existing)
    for name in (n for n in fresh if n not in have):  # a block this template added: before Gotchas, else at the end
        block = f"<!-- gen:begin {name} -->\n{fresh[name]}\n<!-- gen:end {name} -->\n"
        idx = merged.find("\n## Gotchas")
        merged = merged + "\n" + block if idx < 0 else merged[: idx + 1] + block + "\n" + merged[idx + 1 :]
    return merged


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def default_out(repo: Path, app: str) -> Path:
    return repo / ".claude" / "skills" / f"verify-{app}"


def generate(out: Path, outputs: dict[str, str]) -> list[str]:
    """Write every output; returns the relative paths that changed."""
    changed: list[str] = []
    for rel, rendered in outputs.items():
        path = out / rel
        text = merge_blocks(_read(path), rendered) if path.is_file() else rendered
        if path.is_file() and _read(path) == text:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        changed.append(rel)
    return changed


# ---------------------------------------------------------------------- check


def _rows(block: str) -> dict[str, str]:
    """Feature-table rows keyed by sub-feature label + surface name, valued by nodes."""
    rows: dict[str, str] = {}
    for line in block.splitlines():
        m = _ROW_RE.match(line)
        if m and m.group(1) not in ("Sub-feature", "---"):
            rows[f"{m.group(1)} {m.group(2)}".strip()] = m.group(3)
    return rows


def _describe(rel: str, old: dict[str, str], new: dict[str, str]) -> list[str]:
    lines: list[str] = []
    if rel.startswith("features/") and "feature" in old and "feature" in new:
        before, after = _rows(old["feature"]), _rows(new["feature"])
        lines += [f"{rel}: new sub-feature not in the map: {k}" for k in sorted(after.keys() - before.keys())]
        lines += [f"{rel}: mapped sub-feature no longer seeded (test or surface() call gone): {k}" for k in sorted(before.keys() - after.keys())]
        lines += [f"{rel}: driving node changed for: {k}" for k in sorted(before.keys() & after.keys()) if before[k] != after[k]]
        if lines:
            return lines
    return [f"{rel}: generated block `{name}` differs from fresh seeds" for name in sorted(new) if old.get(name) != new[name]]


def static_check(out: Path, outputs: dict[str, str], model: Model) -> tuple[str, list[str]]:
    state, lines = "clean", []

    def worsen(to: str) -> None:
        nonlocal state
        state = max(state, to, key=STATES.index)

    for fill in model.fills:
        worsen("blocked")
        lines.append(f"[verify] incomplete: {fill}; fill it in .fleet.toml (it is never guessed)")
    if not (out / "SKILL.md").is_file():
        return "blocked", lines + [f"no generated skill at {out}: run the generator first"]
    for rel, rendered in outputs.items():
        path = out / rel
        if not path.is_file():
            worsen("changed")
            lines.append(f"{rel}: missing (a new view, or never generated)")
            continue
        committed = _read(path)
        try:
            old, new = blocks(committed), blocks(rendered)
        except GeneratorError as exc:
            worsen("blocked")
            lines.append(f"{rel}: {exc}")
            continue
        if merge_blocks(committed, rendered) != committed:
            worsen("changed")
            lines += _describe(rel, old, new)
    features = out / "features"
    for stale in sorted(p.name for p in features.glob("*.md")) if features.is_dir() else []:
        if f"features/{stale}" not in outputs:
            worsen("changed")
            lines.append(f"features/{stale}: no longer has a seed in the source (left in place)")
    return state, lines


def probe_live(base_url: str, ready_path: str) -> tuple[bool, str]:
    """GET the disposable instance's ready path. Unreachable is its own message, never a pass."""
    url = base_url.rstrip("/") + ready_path
    if not url.startswith(("http://", "https://")):
        return False, f"{url} is not an http(s) URL"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # a disposable loopback instance; never a remote host
    try:
        with urllib.request.urlopen(url, timeout=5, context=ctx) as resp:  # noqa: S310 - scheme checked above
            return (resp.status == 200), f"GET {url} answered {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"GET {url} answered HTTP {exc.code}"
    except (OSError, ValueError) as exc:
        return False, f"GET {url} unreachable: {exc}"


def junit_problems(junit: Path, nodes: list[str]) -> list[str]:
    """Every mapped node must appear in the junit XML and have passed (all parametrized variants)."""
    try:
        root = ET.parse(junit).getroot()
    except (OSError, ET.ParseError) as exc:
        return [f"junit XML {junit} is unreadable: {exc}"]
    results: dict[tuple[str, str], list[str]] = {}
    for case in root.iter("testcase"):
        name = (case.get("name") or "").split("[")[0]
        outcome = next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), "passed")
        results.setdefault((case.get("classname") or "", name), []).append(outcome)
    problems: list[str] = []
    for node in nodes:
        path, *rest = node.split("::")
        classname = ".".join([path.removesuffix(".py").replace("/", "."), *rest[:-1]])
        outcomes = results.get((classname, rest[-1]) if rest else ("", ""), [])
        if not outcomes:
            problems.append(f"{node}: not in the junit XML (never ran)")
        elif any(o != "passed" for o in outcomes):
            problems.append(f"{node}: {', '.join(sorted(set(outcomes) - {'passed'}))}")
    return problems


def run_check(out: Path, outputs: dict[str, str], model: Model, live_url: str | None, junit: Path | None) -> int:
    state, lines = static_check(out, outputs, model)
    for line in lines:
        print(f"STATIC: {line}")
    print(f"STATIC={state}")
    if live_url is None:
        return EXIT[state]
    live_state = state
    reachable, detail = probe_live(live_url, str(model.verify["ready_path"]))
    print(f"LIVE: {detail}")
    if not reachable:
        live_state = "blocked"
    assert junit is not None  # enforced by main()
    for problem in junit_problems(junit, model.nodes):
        print(f"LIVE: {problem}")
        live_state = "blocked"
    if not model.nodes:
        print("LIVE: the map has no driving nodes, so nothing was confirmed")
        live_state = "blocked"
    final = max(state, live_state, key=STATES.index)
    print(f"MAINTAIN={final}")
    return EXIT[final]


# ------------------------------------------------------------------------ cli


GITIGNORE_NOTE = """\
Review the skill, then share it by replacing the blanket `.claude/` ignore rule with this narrow allowlist (docs/agents/project-skills.md):

**/.claude/*
!/.claude/skills/
/.claude/skills/*
!/.claude/skills/verify-{app}/
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--repo", type=Path, required=True, help="the adopter repo root (read only)")
    parser.add_argument("--app", help="app slug (default: the repo folder name)")
    parser.add_argument("--out", type=Path, help="the skill directory to write (default: <repo>/.claude/skills/verify-<app>)")
    parser.add_argument("--check", action="store_true", help="compare fresh seeds with the committed skill; writes nothing")
    parser.add_argument("--live-url", help="with --check: base URL of the disposable instance, probed at ready_path")
    parser.add_argument("--junit", type=Path, help="with --check: pytest junit XML of the mapped nodes")
    args = parser.parse_args(argv)
    if (args.live_url or args.junit) and not args.check:
        parser.error("--live-url and --junit only apply with --check")
    if bool(args.live_url) != bool(args.junit):
        parser.error("--live-url and --junit go together: MAINTAIN needs both, or it cannot be called clean")
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    repo = args.repo.resolve()
    app = args.app or default_app(repo)
    out = (args.out or default_out(repo, app)).resolve()
    try:
        model = build_model(repo, app)
        outputs = render_all(model)
        if args.check:
            return run_check(out, outputs, model, args.live_url, args.junit)
        changed = generate(out, outputs)
    except GeneratorError as exc:
        logger.error("❌ %s", exc)
        print("STATIC=blocked" if args.check else "GENERATE=failed")
        return 2

    for rel in changed:
        logger.info("✅ wrote %s", rel)
    logger.info("ℹ️ %d file(s) changed, %d unchanged -> %s", len(changed), len(outputs) - len(changed), out)
    for fill in model.fills:
        logger.warning("⚠️ %s (a %s placeholder is in SKILL.md; --check stays blocked until it is filled)", fill, FILL)
    for item in model.unresolved:
        logger.warning("⚠️ not mapped: %s", item)
    if args.out is None:
        print(GITIGNORE_NOTE.format(app=app))
    return 0


if __name__ == "__main__":
    sys.exit(main())
