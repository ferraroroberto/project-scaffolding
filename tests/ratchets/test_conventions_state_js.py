"""Tests for the conventions ratchet's state rules over JavaScript and TypeScript.

Same shape as `test_conventions_state.py`, on throwaway git repos: each rule's JS spellings hit
and miss, the `//` exempt marker, test-module and bundle exclusions, a `[[state_machines]]` entry
naming a JS module, and the cross-language rule (a JS site counts a Python spelling as a second
home; a Python site never counts a JS one). The tokenizer's own cases close the file: what sits in
comments, plain template text or regex literals is never read as code, and a file it cannot read
is "not confirmed".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import conventions_ratchet as cr
from scripts import conventions_state as cs
from tests._git_repo import git, write
from tests.ratchets.test_conventions_state import STATE, _toml, scan

# ------------------------------------------------------------- state-literal


def test_state_literal_reads_the_js_comparison_and_store_forms(tmp_path: Path) -> None:
    found = scan(tmp_path, {"web/a.js": (
        "export function f(job, row, params) {\n"
        "  if (job.status === 'running') return 1;\n"       # strict equality against a state holder
        "  if ('failed' !== row['state']) return 2;\n"      # reversed, a string key
        "  row.phase = 'loading';\n"                        # stored
        "  const payload = { status: 'queued' };\n"         # an object literal's state key
        "  if (params.get('stage') == 'done') return 3;\n"  # Map / URLSearchParams get
        "  return ['idle', 'paused'].includes(job?.state);\n"  # membership, one hit per literal
        "}\n"
    )}, ("state-literal",))
    assert found == {"web/a.js": ["state-literal:2", "state-literal:3", "state-literal:4", "state-literal:5",
                                  "state-literal:6", "state-literal:7", "state-literal:7"]}


def test_state_literal_reads_switch_cases_and_set_membership(tmp_path: Path) -> None:
    found = scan(tmp_path, {"web/a.ts": (
        "const LIVE = new Set(['running', 'pending']);\n"
        "export function label(job: Job): string {\n"
        "  if (new Set(['stopped', 'failed']).has(job.status)) return 'over';\n"
        "  switch (job.status) {\n"
        "    case 'running': return 'live';\n"
        "    case 'green': return '?';\n"       # not a lifecycle word
        "  }\n"
        "  switch (kind) { case 'done': return 'kind'; }\n"  # the subject is not a state holder
        "  return LIVE.has(job.status) ? 'live' : 'idle';\n"  # a named set: its spelling is the set rule's
        "}\n"
    )}, ("state-literal",))
    assert found == {"web/a.ts": ["state-literal:3", "state-literal:3", "state-literal:5"]}


def test_state_literal_misses_names_types_comments_and_template_text(tmp_path: Path) -> None:
    found = scan(tmp_path, {"web/a.tsx": (
        "type Job = { status: 'running' | 'failed' };\n"   # a TypeScript union type, not a stored value
        "// if (job.status === 'running') {}\n"            # a comment
        "/* job.status === 'failed' */\n"
        "const text = `job.status === 'done'`;\n"         # plain template text
        "const re = /'/g;\n"                               # a regex literal holding a quote
        "export const View = () => <p>Don't stop</p>;\n"  # a JSX apostrophe
        "if (level === 'running') {}\n"                   # the name does not hold a state
        "if (job.status === 'green') {}\n"                # not a lifecycle word
        "if (job.status === 'running'.trim()) {}\n"       # not a whole operand
    )}, ("state-literal",))
    assert found == {}


def test_state_literal_reads_code_inside_a_template_interpolation(tmp_path: Path) -> None:
    found = scan(tmp_path, {"web/a.js": "const s = `job ${job.status === 'running' ? 'live' : `${n}`}`;\n"},
                 ("state-literal",))
    assert found == {"web/a.js": ["state-literal:1"]}


def test_state_literal_honours_a_reasoned_js_marker_only(tmp_path: Path) -> None:
    found = scan(tmp_path, {"web/a.js": (
        "// state-literal-exempt: the Web Audio API's own vocabulary\n"
        "const a = ctx.state === 'running';\n"
        "const b = ctx.state === 'running'; // state-literal-exempt: same API\n"
        "/* state-literal-exempt: */\n"
        "const c = job.state === 'failed';\n"
    )}, ("state-literal",))
    assert found == {"web/a.js": ["state-literal:5"]}, "a bare marker exempts nothing"


@pytest.mark.parametrize("path", ["web/a.test.js", "web/a.spec.ts", "web/__tests__/a.js", "tests/e2e/a.js",
                                  "web/vendor/lib.min.js"])
def test_state_rules_skip_js_tests_and_minified_bundles(tmp_path: Path, path: str) -> None:
    assert scan(tmp_path, {path: "if (job.status === 'running') {}\n"}) == {}


# --------------------------------------------------------- state-set-repeat

def test_state_set_repeat_reads_arrays_unions_enums_and_enum_objects(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "web/a.js": "export const ACTIVE = ['running', 'pending'];\n",
        "web/b.ts": "type Active = 'pending' | 'running';\n",
        "web/c.ts": "export enum Active { Running = 'running', Pending = 'pending' }\n",
        "web/d.js": "export const Active = Object.freeze({ RUNNING: 'running', PENDING: 'pending' });\n",
        "web/e.js": "export const LABEL = { running: 'Running', pending: 'Pending' };\n",  # keyed by its states
    }, ("state-set-repeat",))
    assert found == {f"web/{n}": ["state-set-repeat:1"] for n in ("a.js", "b.ts", "c.ts", "d.js", "e.js")}


def test_state_set_repeat_misses_records_indexes_and_a_set_kept_in_one_module(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "web/a.js": ("const A = ['running', 'pending'];\nconst B = ['pending', 'running'];\n"
                     "const OPTS = [{ answer: 'done', label: 'Done' }, { answer: 'pending', label: 'Pending' }];\n"),
        "web/b.js": "const x = table['running'];\nconst C = ['running', 'blue'];\n",
    }, ("state-set-repeat",))
    assert found == {}


def test_a_js_site_counts_a_python_spelling_but_a_python_site_never_counts_js(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/jobs.py": "ACTIVE = ('running', 'pending')\n",
        "web/jobs.js": "const ACTIVE = new Set(['pending', 'running']);\n",
    }, ("state-set-repeat",))
    assert found == {"web/jobs.js": ["state-set-repeat:1"]}, "reading JS never changes a Python module's hits"


# --------------------------------------------------------------- state-write

def test_state_write_flags_one_js_flag_written_from_two_modules(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "web/a.js": "export function start(job) {\n  job.ready = false;\n}\n",
        "web/b.ts": "export function done(job: Job) {\n  job['ready'] = job.count === 0;\n}\n",
        "web/c.js": "export function stop(job) {\n  job.ready = !job.live\n}\n",
    }, ("state-write",))
    assert found == {"web/a.js": ["state-write:2"], "web/b.ts": ["state-write:2"], "web/c.js": ["state-write:2"]}


def test_state_write_misses_one_owner_locals_non_flags_and_non_flag_values(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "web/a.js": "class A {\n  go() { this.loading = true; this.loading = false; }\n}\n",
        "web/b.js": ("let ready = true;\njob.pending = [];\njob.ready = compute();\njob.colour = true;\n"
                     "job.ready = job.ready || false;\nconst m = new Map<string, number>();\njob.ready = m\n"),
        "web/c.js": "function g(ready = false) { return ready; }\njob.ready == true;\n",
    }, ("state-write",))
    assert found == {}


def test_state_write_honours_the_js_marker(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "web/a.js": "job.ready = true;\n",
        "web/b.js": "job.ready = false; // state-write-exempt: test double reset\n",
    }, ("state-write",))
    assert found == {"web/a.js": ["state-write:1"]}, "the marked site still counts as a second home"


# --------------------------------------------------------- [[state_machines]]

JS_MACHINE = '''
[[state_machines]]
name   = "job"
module = "web/job-state.js"
type   = "JobState"
derive = "deriveJobState"
'''
JS_DECLARED = (
    "export const JobState = Object.freeze({ RUNNING: 'running', PENDING: 'pending' });\n"
    "export function deriveJobState(job) {\n"
    "  job.ready = true;\n"
    "  if (job.status === 'running') return JobState.RUNNING;\n"
    "  return ['running', 'pending'].includes(job.status) ? JobState.PENDING : null;\n"
    "}\n"
)


def test_a_declared_js_module_is_never_reported_but_still_counts_as_a_home(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "web/job-state.js": JS_DECLARED,
        "web/view.js": "const LIVE = ['pending', 'running'];\njob.ready = false;\n",
    }, STATE, JS_MACHINE)
    assert found == {"web/view.js": ["state-set-repeat:1", "state-write:2"]}


@pytest.mark.parametrize(
    ("source", "declares"),
    [
        pytest.param("export type JobState = 'running' | 'done';\nexport function deriveJobState() {}\n", True,
                     id="type-alias"),
        pytest.param("export enum JobState { A = 'a' }\nexport const deriveJobState = (j) => j;\n", True, id="enum"),
        pytest.param("class JobState {}\nasync function deriveJobState() {}\n", True, id="class"),
        pytest.param("function f() { const JobState = 1; }\nfunction deriveJobState() {}\n", False, id="not-top-level"),
    ],
)
def test_a_js_declaration_resolves_only_top_level_names(source: str, declares: bool) -> None:
    machine = cs.StateMachine("job", "web/job-state.ts", "JobState", "deriveJobState")
    assert (cs.unresolved(machine, source) == []) is declares


def test_a_js_declaration_that_does_not_resolve_is_not_confirmed(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(_toml(machines=JS_MACHINE), encoding="utf-8")
    write(tmp_path, "web/job-state.js", "export function deriveJobState(job) { return null; }\n")
    write(tmp_path, cr.DEFAULT_BASELINE, '{"version": 1, "entries": []}\n')
    assert cr.run(tmp_path, init=False, update=False, allow_additions=False) == cr.EXIT_NOT_CONFIRMED
    assert "defines no JobState" in capsys.readouterr().out


# ----------------------------------------------------------------- tokenizer

@pytest.mark.parametrize(
    "source",
    [
        pytest.param("const s = `never closed;\n", id="template"),
        pytest.param("/* never closed\n", id="comment"),
        pytest.param("function f() {\n", id="unclosed-brace"),
        pytest.param("const a = [1, 2);\n", id="mismatched"),
    ],
)
def test_a_js_file_the_tokenizer_cannot_read_is_not_confirmed(tmp_path: Path, source: str) -> None:
    with pytest.raises(cr.NotConfirmed, match="cannot be tokenized"):
        scan(tmp_path, {"web/a.js": source})


def test_the_tokenizer_keeps_lines_and_reads_regex_after_an_operator_only() -> None:
    toks = cs.tokenize_js("a = b / c / d;\nx = /re'/.test(y)\n`two\nlines` + 'z'\n")
    assert [t.kind for t in toks if t.text in ("/", "re'")] == ["punct", "punct"]
    assert next(t for t in toks if t.kind == "regex").text == "/re'/"
    assert [(t.text, t.line) for t in toks if t.kind == "str"] == [("two\nlines", 3), ("z", 4)]
