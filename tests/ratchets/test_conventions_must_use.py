"""Tests for the conventions ratchet's declarative `must-use` rule.

The entry shape and its config errors, the name resolution, the helper and `paths` scope,
and the gate behaviour on a throwaway git repo. The two older helper rules (`secret-compare`,
`git-wrapper`) run through the same policies; their own tests stay in `test_conventions_ratchet.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import conventions_ratchet as cr
from tests._git_repo import git, write


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return cr.run(root, init=init, update=update, allow_additions=allow)


def baseline_text(root: Path) -> str:
    return (root / cr.DEFAULT_BASELINE).read_text(encoding="utf-8")


SQLITE = '[[conventions_ratchet.must_use]]\ncall = "sqlite3.connect"\nhelper = ["src/db.py"]\nwhy = "one get_db owns the connection"\n'
REQUESTS = (
    '[[conventions_ratchet.must_use]]\ncall = ["requests.get", "requests.post"]\nhelper = ["src/pooled_http.py"]\n'
    'why = "pooled sessions"\npaths = ["src/", "app/"]\n'
)


def must_use_cfg(*tables: str) -> cr.Config:
    cfg = cr.parse_config("[conventions_ratchet]\nenabled = true\n" + "".join(tables))
    assert cfg is not None
    return cfg


def mu_hits(src: str, path: str = "src/a.py", cfg: cr.Config | None = None) -> list[str]:
    """`rule:line` of every hit in one module, with the `must_use` entries that bind it."""
    cfg = cfg or must_use_cfg(SQLITE)
    return [f"{h.rule}:{h.line}" for h in cr.scan_source(src, path, cr.rules_for(path, cfg), cr.entries_for(path, cfg))]


def test_a_must_use_entry_turns_the_rule_on_without_listing_it() -> None:
    cfg = must_use_cfg(SQLITE, REQUESTS)
    assert cfg.rules == ("must-use",)
    assert cfg.must_use[0] == cr.MustUse(("sqlite3.connect",), ("src/db.py",), "one get_db owns the connection")
    assert cfg.must_use[1].calls == ("requests.get", "requests.post")
    assert cfg.must_use[1].paths == ("src/", "app/")
    both = cr.parse_config(f'[conventions_ratchet]\nenabled = true\nrules = ["no-window"]\n{SQLITE}')
    assert both is not None and both.rules == ("no-window", "must-use")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('call = "sqlite3.connect"\nwhy = "x"\n', id="missing-helper"),
        pytest.param('call = "sqlite3.connect"\nhelper = []\nwhy = "x"\n', id="empty-helper"),
        pytest.param('call = "sqlite3.connect"\nhelper = "src/db.py"\nwhy = "x"\n', id="helper-not-a-list"),
        pytest.param('helper = ["src/db.py"]\nwhy = "x"\n', id="missing-call"),
        pytest.param('call = "connect"\nhelper = ["src/db.py"]\nwhy = "x"\n', id="call-not-dotted"),
        pytest.param('call = ["sqlite3.connect", "x y"]\nhelper = ["src/db.py"]\nwhy = "x"\n', id="one-bad-call"),
        pytest.param('call = "sqlite3.connect"\nhelper = ["src/db.py"]\n', id="missing-why"),
        pytest.param('call = "sqlite3.connect"\nhelper = ["src/db.py"]\nwhy = " "\n', id="blank-why"),
        pytest.param('call = "sqlite3.connect"\nhelper = ["src/db.py"]\nwhy = "x"\nhelpers = []\n', id="unknown-key"),
        pytest.param('call = "sqlite3.connect"\nhelper = ["src/db.py"]\nwhy = "x"\npaths = "src/"\n', id="paths-not-a-list"),
    ],
)
def test_a_malformed_must_use_entry_fails_loud(body: str) -> None:
    with pytest.raises(cr.ConfigError):
        cr.parse_config("[conventions_ratchet]\nenabled = true\n[[conventions_ratchet.must_use]]\n" + body)


def test_must_use_needs_an_entry_and_must_be_an_array_of_tables() -> None:
    for body in ('rules = ["must-use"]\n', "must_use = 'x'\n", "must_use = []\n", "must_use = [1]\n"):
        with pytest.raises(cr.ConfigError):
            cr.parse_config("[conventions_ratchet]\nenabled = true\n" + body)


def test_must_use_fails_by_name_on_a_violation_and_passes_the_compliant_form() -> None:
    bad = "import sqlite3\nconn = sqlite3.connect('x.db')\n"
    assert mu_hits(bad) == ["must-use:2"]
    assert mu_hits("from src.db import get_db\nconn = get_db()\n") == []
    message = cr.scan_source(bad, "src/a.py", frozenset({"must-use"}), must_use_cfg(SQLITE).must_use)[0].message
    assert message == "`sqlite3.connect(...)` outside src/db.py: one get_db owns the connection"


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("import sqlite3 as sq\nsq.connect('x')\n", id="module-alias"),
        pytest.param("from sqlite3 import connect\nconnect('x')\n", id="from-import"),
        pytest.param("from sqlite3 import connect as open_db\nopen_db('x')\n", id="from-import-alias"),
        pytest.param("import sqlite3\nwith sqlite3.connect('x') as c:\n    pass\n", id="context-manager"),
    ],
)
def test_must_use_follows_import_aliases(src: str) -> None:
    assert [h.split(":")[0] for h in mu_hits(src)] == ["must-use"]


def test_must_use_resolves_dotted_modules() -> None:
    cfg = must_use_cfg('[[conventions_ratchet.must_use]]\ncall = "urllib.request.urlopen"\n'
                       'helper = ["src/net.py"]\nwhy = "one fetch helper"\n')
    for src in ("import urllib.request\nurllib.request.urlopen(u)\n",
                "from urllib import request\nrequest.urlopen(u)\n",
                "from urllib.request import urlopen\nurlopen(u)\n",
                "import urllib.request as ur\nur.urlopen(u)\n"):
        assert mu_hits(src, cfg=cfg) == ["must-use:2"], src
    assert mu_hits("import urllib.parse\nurllib.parse.quote(u)\n", cfg=cfg) == []


def test_must_use_does_not_guess_what_it_cannot_resolve() -> None:
    assert mu_hits("import sqlite3\nconn.connect('x')\nsqlite3.Connection('x')\n") == []
    assert mu_hits("def connect(p):\n    return p\n\nconnect('x')\n") == []  # a local def, not sqlite3's
    assert mu_hits("from .sqlite3 import connect\nconnect('x')\n") == []  # a relative import is another module


def test_the_helper_file_and_the_entry_paths_decide_where_an_entry_binds() -> None:
    call = "import requests\nrequests.get(u)\nrequests.post(u)\nrequests.put(u)\n"
    cfg = must_use_cfg(REQUESTS)
    assert mu_hits(call, "src/a.py", cfg) == ["must-use:2", "must-use:3"]  # put is not listed
    assert mu_hits(call, "src/pooled_http.py", cfg) == []  # the helper may make the call
    assert mu_hits(call, "scripts/one_shot.py", cfg) == []  # outside the entry's paths
    assert cr.rules_for("src/pooled_http.py", cfg) == frozenset()
    assert cr.rules_for("src/a.py", cfg) == frozenset({"must-use"})


def test_several_entries_bind_independently_and_count_under_one_rule() -> None:
    cfg = must_use_cfg(SQLITE, REQUESTS)
    src = "import sqlite3\nimport requests\nsqlite3.connect('x')\nrequests.get(u)\n"
    assert mu_hits(src, "src/a.py", cfg) == ["must-use:3", "must-use:4"]
    assert mu_hits(src, "src/db.py", cfg) == ["must-use:4"]  # one entry's helper does not excuse the other


def test_must_use_leaves_tests_and_an_exempt_call_alone() -> None:
    assert mu_hits("import sqlite3\nsqlite3.connect('x')\n", "tests/test_a.py") == []
    marked = "import sqlite3\n# must-use-exempt: a long-lived single connection\nsqlite3.connect('x')\n"
    assert mu_hits(marked) == []
    assert mu_hits("import sqlite3\n# must-use-exempt\nsqlite3.connect('x')\n") == ["must-use:3"]
    assert mu_hits("import sqlite3\n# no-window-exempt: x\nsqlite3.connect('x')\n") == ["must-use:3"]


def test_secret_compare_and_git_wrapper_are_must_use_policies_with_their_own_names() -> None:
    assert set(cr.BUILTIN_POLICIES) == set(cr.REQUIRED_KEYS)
    for rule, policy in cr.BUILTIN_POLICIES.items():
        assert policy.rule == rule
    # One scan carries the built-in and the declared policies together, each reporting under its own rule.
    cfg = cr.Config(cr.DEFAULT_BASELINE, ("secret-compare", "git-wrapper", "must-use"), (), cr.DEFAULT_PRINT_PATHS,
                    ("src/s.py",), ("src/g.py",), must_use_cfg(SQLITE).must_use)
    src = ("import hmac\nimport sqlite3\nimport subprocess\nhmac.compare_digest(a, b)\n"
           "sqlite3.connect('x')\nsubprocess.run(['git', 'log'], creationflags=0)\n")
    assert mu_hits(src, cfg=cfg) == ["secret-compare:4", "must-use:5", "git-wrapper:6"]


def must_use_repo(root: Path, *tables: str) -> Path:
    git(root, "init", "-q")
    (root / ".fleet.toml").write_text("[conventions_ratchet]\nenabled = true\n" + "".join(tables), encoding="utf-8")
    write(root, "src/db.py", "import sqlite3\n\n\ndef get_db():\n    return sqlite3.connect('x.db')\n")
    write(root, "src/a.py", "import sqlite3\n\nOLD = sqlite3.connect('old.db')\n")
    return root


def test_a_new_must_use_hit_fails_the_gate_beyond_its_baseline(tmp_path: Path,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    repo = must_use_repo(tmp_path, SQLITE)
    assert run_mode(repo, init=True) == cr.EXIT_PASS
    assert baseline_text(repo).count('"must-use": 1') == 1  # the helper's own call is not a hit
    assert run_mode(repo) == cr.EXIT_PASS
    write(repo, "src/b.py", "import sqlite3\n\nNEW = sqlite3.connect('new.db')\n")
    capsys.readouterr()
    assert run_mode(repo) == cr.EXIT_RISE
    out = capsys.readouterr().out
    assert "src/b.py: [must-use] 1 hit(s), baseline 0:" in out
    assert "src/b.py:3: [must-use] `sqlite3.connect(...)` outside src/db.py: one get_db owns the connection" in out


def test_a_burned_down_must_use_baseline_shrinks_to_zero(tmp_path: Path) -> None:
    repo = must_use_repo(tmp_path, SQLITE)
    run_mode(repo, init=True)
    write(repo, "src/a.py", "from src.db import get_db\n\nOLD = get_db()\n")
    assert run_mode(repo, update=True) == cr.EXIT_PASS
    assert '"entries": []' in baseline_text(repo)


def test_a_must_use_entry_with_no_helper_exits_two_in_every_mode(tmp_path: Path) -> None:
    repo = must_use_repo(tmp_path, '[[conventions_ratchet.must_use]]\ncall = "sqlite3.connect"\nwhy = "x"\n')
    for kwargs in ({}, {"init": True}, {"update": True}):
        assert run_mode(repo, **kwargs) == cr.EXIT_CONFIG
