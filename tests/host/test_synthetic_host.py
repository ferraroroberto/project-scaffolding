"""The `synthetic_host` fixture: every stdlib way of asking for the account or home answers with the fake."""

from __future__ import annotations

import getpass
import os
from pathlib import Path

from tests.host._synthetic_host import SYNTHETIC_ACCOUNT, SyntheticHost, synthetic_host_env


def test_the_fixture_fakes_account_and_home(synthetic_host: SyntheticHost, tmp_path: Path) -> None:
    assert synthetic_host.account == SYNTHETIC_ACCOUNT
    assert synthetic_host.home.is_dir() and synthetic_host.home.is_relative_to(tmp_path)
    # host-identity-exempt: this test proves the stdlib reads now answer with the fake values
    assert getpass.getuser() == SYNTHETIC_ACCOUNT
    # host-identity-exempt: this test proves the stdlib reads now answer with the fake values
    assert Path.home() == synthetic_host.home
    # host-identity-exempt: this test proves the stdlib reads now answer with the fake values
    assert Path(os.path.expanduser("~")) == synthetic_host.home


def test_the_interpreter_path_lives_under_the_fake_home(synthetic_host: SyntheticHost) -> None:
    assert Path(synthetic_host.python).is_relative_to(synthetic_host.home)


def test_the_child_env_keeps_everything_else_and_replaces_identity(tmp_path: Path) -> None:
    env = synthetic_host_env({"PATH": "p", "USERNAME": "someone", "HOME": "elsewhere"}, tmp_path)
    assert env["PATH"] == "p"
    assert env["USERNAME"] == env["USER"] == env["LOGNAME"] == SYNTHETIC_ACCOUNT
    home = Path(env["HOME"])
    assert home.is_dir() and Path(env["USERPROFILE"]) == home
    drive, rest = os.path.splitdrive(str(home))
    assert env.get("HOMEDRIVE", "") == drive and (env.get("HOMEPATH") == rest if drive else "HOMEPATH" not in env)
