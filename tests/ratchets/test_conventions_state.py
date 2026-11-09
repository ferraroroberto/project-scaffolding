"""Tests for the conventions ratchet's implicit-state-machine rules and `[[state_machines]]`.

Each rule is exercised on a throwaway git repo, because two of the three only fire when a
spelling appears in more than one module: a hit, a miss, the exempt marker, and the declared
module's exemption. The declaration table's validation closes the file: a malformed table is a
configuration error, and a declared module that is missing is "not confirmed", never a skip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import conventions_ratchet as cr
from tests._git_repo import git, write

STATE = ("state-literal", "state-set-repeat", "state-write")


def _toml(rules: tuple[str, ...] = STATE, machines: str = "") -> str:
    listed = ", ".join(f'"{r}"' for r in rules)
    return f"[conventions_ratchet]\nenabled = true\nrules = [{listed}]\n{machines}"


def scan(root: Path, files: dict[str, str], rules: tuple[str, ...] = STATE, machines: str = "") -> dict[str, list[str]]:
    """`rule:line` per file of every hit in a repo holding `files`."""
    git(root, "init", "-q")
    (root / ".fleet.toml").write_text(_toml(rules, machines), encoding="utf-8")
    for rel, text in files.items():
        write(root, rel, text)
    cfg, vendored = cr.load_config(root)
    assert cfg is not None
    return {p: [f"{h.rule}:{h.line}" for h in hs] for p, hs in cr.scan_tree(root, cfg, vendored).items()}


MACHINE = '''
[[state_machines]]
name   = "job"
module = "src/job_state.py"
type   = "JobState"
derive = "derive_job_state"
'''
DECLARED = (
    "import enum\n\n\nclass JobState(enum.StrEnum):\n    RUNNING = 'running'\n    PENDING = 'pending'\n\n\n"
    "def derive_job_state(job):\n    job.ready = True\n    if job.status == 'running':\n        return JobState.RUNNING\n"
    "    return JobState.PENDING if job.status in ('running', 'pending') else None\n"
)


def test_the_three_rules_are_registered_and_opt_in() -> None:
    assert set(STATE) <= set(cr.RULES)
    cfg = cr.parse_config(_toml(("no-window",)))
    assert cfg is not None and not set(STATE) & set(cfg.rules)


# ------------------------------------------------------------- state-literal

def test_state_literal_flags_a_lifecycle_string_compared_or_stored_as_a_state(tmp_path: Path) -> None:
    found = scan(tmp_path, {"src/a.py": (
        "def f(job, row):\n"
        "    if job.status == 'running':\n"          # compared to an attribute named status
        "        row['state'] = 'failed'\n"           # stored under a state key
        "    return row.get('phase') in ('idle', 'loading')\n"  # membership, one hit per literal
        "PAYLOAD = {'status': 'queued'}\n"            # a dict literal's state key
        "RUN = dict(stage='done')\n"                  # a state keyword argument
    )}, ("state-literal",))
    assert found == {"src/a.py": ["state-literal:2", "state-literal:3", "state-literal:4", "state-literal:4",
                                  "state-literal:5", "state-literal:6"]}


def test_state_literal_misses_what_does_not_name_a_state(tmp_path: Path) -> None:
    found = scan(tmp_path, {"src/a.py": (
        "def f(level, mode, job):\n"
        "    if level == 'running':\n"     # the name does not say it holds a state
        "        word = 'failed'\n"        # a local that is not a state holder
        "    job.status = 'green'\n"      # not a lifecycle word
        "    return mode\n"
    )}, ("state-literal",))
    assert found == {}


def test_state_literal_honours_a_reasoned_marker_only(tmp_path: Path) -> None:
    found = scan(tmp_path, {"src/a.py": (
        "def f(job):\n"
        "    # state-literal-exempt: the remote API's own status vocabulary\n"
        "    a = job.status == 'running'\n"
        "    # state-literal-exempt:\n"
        "    b = job.status == 'failed'\n"
        "    return a, b\n"
    )}, ("state-literal",))
    assert found == {"src/a.py": ["state-literal:5"]}, "a bare marker exempts nothing"


def test_state_literal_skips_test_modules_and_the_declared_module(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/job_state.py": DECLARED,
        "tests/test_a.py": "def test_x(job):\n    assert job.status == 'running'\n",
    }, ("state-literal",), MACHINE)
    assert found == {}


# --------------------------------------------------------- state-set-repeat

def test_state_set_repeat_flags_one_state_set_spelled_in_two_modules(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/a.py": "ACTIVE = ('running', 'pending')\n",
        "src/b.py": "def live(s):\n    return s in {'pending', 'running'}\n",
        "src/c.py": "LIVE = frozenset({'running', 'pending'})\n",  # one set, not the call and its literal
    }, ("state-set-repeat",))
    assert found == {"src/a.py": ["state-set-repeat:1"], "src/b.py": ["state-set-repeat:2"],
                     "src/c.py": ["state-set-repeat:1"]}


def test_state_set_repeat_misses_a_set_kept_in_one_module_or_without_two_states(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/a.py": "A = ('running', 'pending')\nB = ['running', 'pending']\nC = ('running', 'blue')\n",
        "src/b.py": "C = ('running', 'blue')\nD = ('running', 'pending', 'failed')\n",
    }, ("state-set-repeat",))
    assert found == {}


def test_state_set_repeat_sees_enum_and_literal_spellings(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/a.py": "import enum\n\n\nclass S(enum.Enum):\n    A = 'running'\n    B = 'stopped'\n",
        "src/b.py": "from typing import Literal\n\nS = Literal['stopped', 'running']\n",
    }, ("state-set-repeat",))
    assert found == {"src/a.py": ["state-set-repeat:4"], "src/b.py": ["state-set-repeat:3"]}


def test_state_set_repeat_marker_clears_one_site_only(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/a.py": "# state-set-repeat-exempt: mirrors the wire format\nACTIVE = ('running', 'pending')\n",
        "src/b.py": "ACTIVE = ('running', 'pending')\n",
    }, ("state-set-repeat",))
    assert found == {"src/b.py": ["state-set-repeat:1"]}, "the marked site still counts as a second home"


def test_state_set_repeat_counts_the_declared_module_but_never_reports_it(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/job_state.py": DECLARED,
        "src/b.py": "ACTIVE = ('pending', 'running')\n",
    }, ("state-set-repeat",), MACHINE)
    assert found == {"src/b.py": ["state-set-repeat:1"]}


# --------------------------------------------------------------- state-write

def test_state_write_flags_one_flag_written_from_two_modules(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/a.py": "def start(job):\n    job.ready = False\n",
        "src/b.py": "def done(job):\n    setattr(job, 'ready', True)\n",
    }, ("state-write",))
    assert found == {"src/a.py": ["state-write:2"], "src/b.py": ["state-write:2"]}


def test_state_write_misses_one_owner_locals_and_non_flags(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/a.py": "class A:\n    def go(self):\n        self._loading = True\n        self._loading = False\n",
        "src/b.py": "def f(job):\n    ready = True\n    job.ready = compute()\n    job.colour = True\n",
        "src/c.py": "def g():\n    ready = False\n    return ready\n",
    }, ("state-write",))
    assert found == {}


def test_state_write_honours_the_marker_and_the_declared_module(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/job_state.py": DECLARED,
        "src/b.py": "def f(job):\n    job.ready = True\n",
        "src/c.py": "def g(job):\n    job.ready = False  # state-write-exempt: test double reset\n",
    }, ("state-write",), MACHINE)
    assert found == {"src/b.py": ["state-write:2"]}


# --------------------------------------------------------- [[state_machines]]

def test_state_machines_table_is_parsed() -> None:
    cfg = cr.parse_config(_toml(machines=MACHINE))
    assert cfg is not None
    assert cfg.state_machines == (cr.StateMachine("job", "src/job_state.py", "JobState", "derive_job_state"),)


@pytest.mark.parametrize(
    "machines",
    [
        pytest.param('[[state_machines]]\nmodule = "a.py"\ntype = "S"\n', id="no-name"),
        pytest.param('[[state_machines]]\nname = "x"\ntype = "S"\n', id="no-module"),
        pytest.param('[[state_machines]]\nname = "x"\nmodule = "a.py"\n', id="no-type"),
        pytest.param('[[state_machines]]\nname = "x"\nmodule = "a.py"\ntype = "S"\nderiv = "d"\n', id="typo-key"),
        pytest.param('[[state_machines]]\nname = "x"\nmodule = "a.py"\ntype = "S"\nderive = 3\n', id="derive-not-str"),
        pytest.param('state_machines = "a.py"\n', id="not-an-array"),
    ],
)
def test_a_malformed_state_machines_table_is_a_config_error(machines: str) -> None:
    with pytest.raises(cr.ConfigError):
        cr.parse_config(_toml(machines=machines))


@pytest.mark.parametrize(
    ("module", "body"),
    [
        pytest.param("src/missing.py", None, id="module-missing"),
        pytest.param("src/job_state.py", "def derive_job_state(job):\n    return None\n", id="type-missing"),
        pytest.param("src/job_state.py", "class JobState:\n    pass\n", id="derive-missing"),
    ],
)
def test_a_declaration_that_does_not_resolve_is_not_confirmed(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], module: str, body: str | None) -> None:
    git(tmp_path, "init", "-q")
    machines = MACHINE.replace("src/job_state.py", module)
    (tmp_path / ".fleet.toml").write_text(_toml(machines=machines), encoding="utf-8")
    if body is not None:
        write(tmp_path, module, body)
    write(tmp_path, cr.DEFAULT_BASELINE, '{"version": 1, "entries": []}\n')
    assert cr.run(tmp_path, init=False, update=False, allow_additions=False) == cr.EXIT_NOT_CONFIRMED
    assert "NOT CONFIRMED" in capsys.readouterr().out


def test_a_declared_type_alias_resolves(tmp_path: Path) -> None:
    found = scan(tmp_path, {
        "src/job_state.py": "from typing import Literal\n\nJobState = Literal['running', 'pending']\n\n\n"
                            "def derive_job_state(job):\n    return 'running'\n",
    }, ("state-literal",), MACHINE)
    assert found == {}
