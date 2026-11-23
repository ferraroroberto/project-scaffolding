"""`exclude_by_rule`: switch one rule off under some globs without hiding the files from the other rules.

The plain `exclude` drops a file from every rule. A repo that keeps `no-window` off its test modules would
thereby also switch off `host-identity`, which reads test modules only: listed, enabled, and scanning nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import conventions_ratchet as cr
from tests._git_repo import git, write

BOTH = ("no-window", "host-identity")
TOML = (
    '[conventions_ratchet]\nenabled = true\nrules = ["no-window", "host-identity"]\n'
    'exclude_by_rule = { no-window = ["tests/**"] }\n'
)
SEEDED = "from pathlib import Path\n\ndef test_home():\n    assert Path.home()\n"
SPAWN = "import subprocess\n\ndef test_spawn():\n    subprocess.run(['x'])\n"


def run(root: Path, *, init: bool = False) -> int:
    return cr.run(root, init=init, update=False, allow_additions=False)


def test_the_table_is_parsed_into_the_config() -> None:
    cfg = cr.parse_config(TOML)
    assert cfg is not None
    assert cfg.exclude_by_rule == (("no-window", ("tests/**",)),)
    assert cfg.exclude == ()


def test_a_repo_without_the_key_is_unchanged() -> None:
    cfg = cr.parse_config('[conventions_ratchet]\nenabled = true\nrules = ["no-window"]\n')
    assert cfg is not None and cfg.exclude_by_rule == ()
    assert cr.rules_for("tests/test_a.py", cfg) == {"no-window"}


@pytest.mark.parametrize(
    "line",
    [
        pytest.param("exclude_by_rule = ['tests/**']", id="not-a-table"),
        pytest.param("exclude_by_rule = { no-window = 'tests/**' }", id="globs-not-a-list"),
        pytest.param("exclude_by_rule = { no-window = [1] }", id="glob-not-a-string"),
        pytest.param("exclude_by_rule = { no-windows = ['tests/**'] }", id="unknown-rule"),
        pytest.param("exclude_by_rule = { host-identity = ['tests/**'] }", id="rule-not-enabled"),
    ],
)
def test_a_malformed_table_fails_loud(line: str) -> None:
    with pytest.raises(cr.ConfigError):
        cr.parse_config(f'[conventions_ratchet]\nenabled = true\nrules = ["no-window"]\n{line}\n')


def test_the_excluded_rule_is_dropped_and_the_others_stay() -> None:
    cfg = cr.parse_config(TOML)
    assert cfg is not None
    assert cr.rules_for("tests/test_a.py", cfg) == {"host-identity"}
    assert cr.rules_for("tools/test_a.py", cfg) == {"no-window", "host-identity"}
    assert cr.rules_for("src/a.py", cfg) == {"no-window"}


def test_the_plain_exclude_still_hides_a_file_from_every_rule() -> None:
    cfg = cr.parse_config(TOML.replace("exclude_by_rule", 'exclude = ["tests/**"]\nexclude_by_rule'))
    assert cfg is not None
    assert not cr.in_scope("tests/test_a.py", cfg, ())


def test_a_repo_excluding_tests_for_no_window_still_fails_on_a_seeded_home_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(TOML, encoding="utf-8")
    write(tmp_path, "tests/test_ok.py", "def test_ok(synthetic_host):\n    assert synthetic_host.home\n")
    write(tmp_path, "tests/test_spawn.py", SPAWN)
    assert run(tmp_path, init=True) == cr.EXIT_PASS
    assert run(tmp_path) == cr.EXIT_PASS, "a test spawn is the exemption this repo declared, never a hit"

    write(tmp_path, "tests/test_home.py", SEEDED)
    capsys.readouterr()
    assert run(tmp_path) == cr.EXIT_RISE
    assert "tests/test_home.py:4: [host-identity]" in capsys.readouterr().out
