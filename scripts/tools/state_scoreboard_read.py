"""The state scoreboard's readers: one repo's committed state at one commit, never its working tree.

Every read goes through `run_git` at a resolved commit sha, so two runs at the same commit read the
same bytes. Nothing here writes to a repo. A fact the readers cannot establish is raised as
`ReadError` (or returned as `None` where "absent" is a real answer), never defaulted to zero.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.conventions_state import (  # noqa: E402 -- needs the sys.path line above
    JS_DECLARES,
    JS_SUFFIXES,
    NO_TOK,
    StateMachine,
    Tok,
    is_js_source,
    js_parse,
    parse_machines,
)
from src.no_window import NO_WINDOW  # noqa: E402 -- needs the sys.path line above

STATE_RULES = ("state-literal", "state-set-repeat", "state-write")
DEFAULT_BASELINE = ".conventions-ratchet-baseline.json"
# The marker a test carries to prove its machine refuses an illegal transition.
PROOF_MARKER = "state-machine-proof:"
_PROOF_RE = re.compile(r"state-machine-proof:\s*([A-Za-z0-9_.-]+)")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$")
# One git call on a local repo; far past a slow disk, short of a wedge.
GIT_TIMEOUT_S = 60


class ReadError(RuntimeError):
    """A fact about a repo at a commit could not be established."""


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """`git <args>` in `repo` without taking an index lock; a spawn failure or timeout is a `ReadError`."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, timeout=GIT_TIMEOUT_S,
                              creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReadError(f"git {args[0]} failed to run: {exc}") from exc


def _stderr(done: subprocess.CompletedProcess[bytes]) -> str:
    lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
    return lines[-1] if lines else f"exit {done.returncode}"


def is_date(text: str) -> bool:
    """Whether `--at` names a moment (`2026-11-09`, `2026-11-09T12:00`) rather than a revision."""
    return bool(_DATE_RE.match(text))


def epoch(text: str) -> int:
    moment = dt.datetime.fromisoformat(text.replace(" ", "T")).replace(tzinfo=dt.UTC)
    return int(moment.timestamp())


DEFAULT_BRANCH = "default"


def _remote_default(repo: Path) -> str | None:
    head = run_git(repo, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    return head.stdout.decode().strip() if head.returncode == 0 else None


def resolve_ref(repo: Path, at: str) -> str | None:
    """The commit sha `at` names in `repo`; `None` when a date predates the repo's history.

    A date is read as UTC and resolved on the repo's default branch (`origin/HEAD`, else `HEAD`);
    `default` is that branch's tip, so a checkout that has fallen behind or sits on a feature branch
    still reports the shipped state. Any other value is a revision. A revision the repo does not have
    (or a `default` with no `origin/HEAD`) is a `ReadError`.
    """
    if at == DEFAULT_BRANCH:
        at = _remote_default(repo) or ""
        if not at:
            raise ReadError("no origin/HEAD to resolve 'default' against")
    if is_date(at):
        branch = _remote_default(repo) or "HEAD"
        done = run_git(repo, "rev-list", "-1", "--first-parent", f"--before={epoch(at)}", branch)
        if done.returncode != 0:
            raise ReadError(f"cannot list history of {branch}: {_stderr(done)}")
        return done.stdout.decode().strip() or None
    done = run_git(repo, "rev-parse", "--verify", "-q", f"{at}^{{commit}}")
    if done.returncode != 0:
        raise ReadError(f"revision {at!r} not found")
    return done.stdout.decode().strip()


def read_file(repo: Path, sha: str, path: str) -> str | None:
    """The text of `path` at `sha`; `None` when the commit has no such file."""
    listed = run_git(repo, "ls-tree", "--name-only", sha, "--", path)
    if listed.returncode != 0:
        raise ReadError(f"cannot list {path} at {sha[:7]}: {_stderr(listed)}")
    if not listed.stdout.strip():
        return None
    shown = run_git(repo, "show", f"{sha}:{path}")
    if shown.returncode != 0:
        raise ReadError(f"cannot read {path} at {sha[:7]}: {_stderr(shown)}")
    try:
        return shown.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReadError(f"{path} at {sha[:7]} is not UTF-8") from exc


def parse_config(text: str) -> dict[str, Any]:
    """The parsed `.fleet.toml`; a malformed file is a `ReadError`."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ReadError(f".fleet.toml does not parse: {exc}") from exc


def read_machines(config: dict[str, Any]) -> tuple[StateMachine, ...]:
    """The declared `[[state_machines]]`; a malformed table is a `ReadError`."""
    try:
        return parse_machines(config.get("state_machines", []))
    except ValueError as exc:
        raise ReadError(str(exc)) from exc


def enrolled_rules(config: dict[str, Any]) -> tuple[str, ...]:
    """The state rules the repo's conventions ratchet enforces; empty when it is not enrolled."""
    table = config.get("conventions_ratchet")
    if not isinstance(table, dict) or table.get("enabled") is not True:
        return ()
    rules = table.get("rules", [])
    if not isinstance(rules, list):
        raise ReadError("[conventions_ratchet] rules must be a list")
    return tuple(r for r in STATE_RULES if r in rules)


def _bucket(key: str) -> str:
    return "py" if PurePosixPath(key).suffix == ".py" else "js"


def read_findings(repo: Path, sha: str, config: dict[str, Any], rules: tuple[str, ...]) -> dict[str, dict[str, int]]:
    """Per enrolled rule, the committed baseline's count in Python files (`py`) and any other file (`js`)."""
    table = config["conventions_ratchet"]
    path = table.get("baseline", DEFAULT_BASELINE)
    if not isinstance(path, str) or not path.strip():
        raise ReadError("[conventions_ratchet] baseline must be a non-empty string")
    text = read_file(repo, sha, path)
    if text is None:
        raise ReadError(f"baseline {path} is not committed")
    try:
        entries = json.loads(text)["entries"]
        out = {rule: {"py": 0, "js": 0} for rule in rules}
        for entry in entries:
            for rule, count in entry["counts"].items():
                if rule not in out:
                    continue
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    raise ValueError(f"count {count!r} for {rule}")
                out[rule][_bucket(entry["key"])] += count
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ReadError(f"baseline {path} is malformed: {exc}") from exc
    return out


def _is_test_path(path: str) -> bool:
    """A Python or JS/TS file in a `tests/` or `test/` folder, or named like a test (`test_*.py`, `*_test.py`, `*.test.*`, `*.spec.*`)."""
    pure = PurePosixPath(path)
    in_test_folder = bool({"tests", "test"} & set(pure.parts[:-1]))
    if pure.suffix == ".py":
        return in_test_folder or pure.name.startswith("test_") or pure.name.endswith("_test.py")
    if is_js_source(path):
        return in_test_folder or bool(re.search(r"\.(test|spec)\.[^.]+$", pure.name, re.IGNORECASE))
    return False


def _proof_files(repo: Path, sha: str) -> list[str]:
    pathspecs = ["*.py", *(f"*{suffix}" for suffix in JS_SUFFIXES)]
    done = run_git(repo, "grep", "-I", "-l", "-z", "-e", PROOF_MARKER, sha, "--", *pathspecs)
    if done.returncode == 1:
        return []
    if done.returncode != 0:
        raise ReadError(f"cannot search for proof tests at {sha[:7]}: {_stderr(done)}")
    prefix = f"{sha}:"
    names = (item.decode("utf-8", "replace") for item in done.stdout.split(b"\0") if item)
    return sorted(n[len(prefix):] for n in names if n.startswith(prefix) and _is_test_path(n[len(prefix):]))


def _proofs_in(text: str, path: str) -> list[set[str]]:
    """For each test function in a module, the machine names its marker comments or docstring carry."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise ReadError(f"{path} does not parse: {exc.msg}") from exc
    lines = text.splitlines()
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or not node.name.startswith("test"):
            continue
        first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        while first > 1 and lines[first - 2].lstrip().startswith("#"):
            first -= 1  # the comment block right above the def belongs to the test
        names = set(_PROOF_RE.findall("\n".join(lines[first - 1:node.end_lineno])))
        if names:
            found.append(names)
    return found


_JS_TEST_CALLS = frozenset({"test", "it"})
_JS_TEST_MODIFIERS = frozenset({"only", "skip", "todo", "concurrent", "serial", "fails", "fixme"})


def _js_test_calls(toks: list[Tok], pairs: dict[int, int]) -> list[tuple[int, int]]:
    """The (first line, last line) of each `test(...)` / `it(...)` call, with `.only` / `.skip` style modifiers."""
    spans = []
    for k, tok in enumerate(toks):
        if tok.kind != "name" or tok.text not in _JS_TEST_CALLS or (k and toks[k - 1].text in (".", "?.")):
            continue
        opener = k + 1
        if opener + 2 < len(toks) and toks[opener].text == "." and toks[opener + 1].text in _JS_TEST_MODIFIERS:
            opener += 2
        if opener < len(toks) and toks[opener].kind == "punct" and toks[opener].text == "(" and opener in pairs:
            spans.append((tok.line, toks[pairs[opener]].line))
    return spans


def _js_proofs_in(text: str, path: str) -> list[set[str]]:
    """For each `test`/`it` call in a JS/TS module, the machine names its marker comments carry.

    A marker counts in the comment block that ends on the line right above the call, or in a comment
    inside the call. Comments are read from the tokenizer, so a marker in a string counts for nothing.
    """
    comments: list[tuple[int, int, str]] = []
    try:
        toks, pairs = js_parse(text, comments)
    except ValueError as exc:
        raise ReadError(f"{path} does not parse: {exc}") from exc
    code_lines = {t.line for t in toks}
    own_line = [c for c in comments if c[0] not in code_lines]  # a trailing comment belongs to its code line
    found = []
    for first, last in _js_test_calls(toks, pairs):
        wanted = [c for c in comments if first <= c[0] <= last]
        above = first
        for start, end, body in reversed(own_line):
            if end == above - 1:
                wanted.append((start, end, body))
                above = start
        names = set(_PROOF_RE.findall("\n".join(body for _, _, body in wanted)))
        if names:
            found.append(names)
    return found


def count_proofs(repo: Path, sha: str, machines: tuple[StateMachine, ...]) -> dict[str, int]:
    """Per declared machine, the Python test functions and JS/TS `test`/`it` calls carrying `state-machine-proof: <name>`."""
    counts = {m.name: 0 for m in machines}
    for path in _proof_files(repo, sha):
        text = read_file(repo, sha, path)
        if text is None:
            raise ReadError(f"{path} vanished at {sha[:7]}")
        for names in (_proofs_in if path.endswith(".py") else _js_proofs_in)(text, path):
            for name in names & counts.keys():
                counts[name] += 1
    return counts


def _strings(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def state_names(source: str, type_name: str) -> list[str]:
    """The lower-cased state names a Python owner module gives its declared type; empty when unreadable.

    A class contributes its member names and string values, a `Literal[...]` alias its strings.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == type_name:
            for item in node.body:
                if isinstance(item, ast.Assign):
                    found.update(t.id for t in item.targets if isinstance(t, ast.Name))
                    found.update(_strings(item.value))
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == type_name for t in node.targets):
            found.update(_strings(node.value))
    return sorted({s.lower() for s in found if s.isidentifier() and not s.startswith("_")})


def _js_body_names(toks: list[Tok], pairs: dict[int, int], opener: int) -> set[str]:
    """The member names and string values directly inside one `{...}` or `[...]`: enum, object, class body or array."""
    close, found, j = pairs[opener], set[str](), opener + 1
    while j < close:
        tok, nxt = toks[j], toks[j + 1]
        if tok.kind == "punct" and tok.text in ("(", "[", "{"):
            j = pairs[j] + 1  # a method, a nested value: not a member of this body
            continue
        if tok.kind == "str" and toks[opener].text == "[":
            found.add(tok.text)
        elif tok.kind in ("name", "str") and nxt.kind == "punct" and nxt.text in (":", "="):
            found.add(tok.text)
            if toks[j + 2].kind == "str":
                found.add(toks[j + 2].text)
        elif tok.kind == "name" and toks[opener].text == "{" and toks[j - 1].text in ("{", ",") and (
                j + 1 == close or nxt.text == ","):
            found.add(tok.text)  # a bare enum member: `enum S { A, B }`
        j += 1
    return found


def _js_declared_values(toks: list[Tok], pairs: dict[int, int], k: int) -> set[str]:
    """The state names of the declaration whose keyword is at `k` and whose name follows it."""
    keyword, j = toks[k].text, k + 2
    if keyword == "type":  # `type S = 'a' | 'b'`: the string literals of one union
        found = set[str]()
        while j < len(toks) and (toks[j].kind == "str" or toks[j].text in ("=", "|")):
            if toks[j].kind == "str":
                found.add(toks[j].text)
            j += 1
        return found
    while j < len(toks) and toks[j].text not in ("{", "[", ";"):
        if toks[j].text in ("(", "=", ".", "new", "extends", "implements") or toks[j].kind == "name":
            j += 1
        else:
            return set()  # `const S = compute(...)`: no literal body to read
    return _js_body_names(toks, pairs, j) if j < len(toks) and toks[j].text != ";" else set()


def js_state_names(source: bytes | str, type_name: str) -> list[str]:
    """The lower-cased state names a JS/TS owner module gives its declared type; empty when unreadable.

    Mirrors the Python reader: an `enum`, a `class`, an object or array bound by `const`, `let` or `var`
    contributes its member names and string values, a `type` alias its string-literal union.
    """
    try:
        toks, pairs = js_parse(source)
    except ValueError:
        return []
    toks = [*toks, NO_TOK, NO_TOK, NO_TOK]
    found: set[str] = set()
    depth = 0
    for k, tok in enumerate(toks):
        if tok.kind == "punct" and tok.text in ("(", "[", "{"):
            depth += 1
        elif tok.kind == "punct" and tok.text in (")", "]", "}"):
            depth -= 1
        elif depth == 0 and tok.kind == "name" and tok.text in JS_DECLARES - {"function", "interface"} \
                and toks[k + 1].kind == "name" and toks[k + 1].text == type_name:
            found |= _js_declared_values(toks, pairs, k)
    return sorted({s.lower() for s in found if s.isidentifier() and not s.startswith("_")})
