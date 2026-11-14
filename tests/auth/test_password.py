"""Tests for the vendored app password (`src/password.py`).

Every test points ``APP_PASSWORD_FILE`` at a temp file, so no run reads or
writes the live ``config/app_password.json``. The passwords are fixtures.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from src import password


@pytest.fixture
def pw_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "config" / "app_password.json"
    monkeypatch.setenv(password.ENV_VAR, str(target))
    return target


def test_env_override_wins(pw_file: Path) -> None:
    assert password.password_file() == pw_file


def test_default_path_is_config_beside_src(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(password.ENV_VAR, raising=False)
    assert password.password_file() == Path(password.__file__).resolve().parent.parent / "config" / "app_password.json"


@pytest.mark.parametrize("secret", ["1234", "correct horse battery staple", "pässwörd-ñ", "x"])
def test_any_non_empty_password_round_trips(pw_file: Path, secret: str) -> None:
    password.set_password(secret)
    assert password.check_password(secret)
    assert not password.check_password(secret + "!")
    assert password.is_configured()


def test_stored_file_holds_only_a_salted_hash(pw_file: Path) -> None:
    password.set_password("1234")
    data = json.loads(pw_file.read_text(encoding="utf-8"))
    assert list(data) == [password.HASH_KEY]
    assert "1234" not in pw_file.read_text(encoding="utf-8")
    first = data[password.HASH_KEY]
    password.set_password("1234")
    assert json.loads(pw_file.read_text(encoding="utf-8"))[password.HASH_KEY] != first


def test_empty_password_is_rejected(pw_file: Path) -> None:
    with pytest.raises(ValueError):
        password.set_password("")
    assert not pw_file.exists()


def test_empty_presented_is_always_refused(pw_file: Path) -> None:
    assert not password.check_password("", legacy="")
    assert not password.check_password("", legacy="old")


def test_legacy_password_works_until_the_setter_runs(pw_file: Path) -> None:
    assert password.is_configured(legacy="old-one")
    assert password.check_password("old-one", legacy="old-one")
    assert not password.check_password("wrong", legacy="old-one")
    password.set_password("new-one")
    assert password.check_password("new-one", legacy="old-one")
    assert not password.check_password("old-one", legacy="old-one")


def test_nothing_configured(pw_file: Path) -> None:
    assert not password.is_configured()
    assert not password.check_password("anything")


def test_non_ascii_legacy_compare_does_not_raise(pw_file: Path) -> None:
    assert password.check_password("clé", legacy="clé")
    assert not password.check_password("cle", legacy="clé")


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", json.dumps({"password_hash": 5}), json.dumps({"password_hash": "plaintext"})],
)
def test_broken_file_falls_back_to_legacy(pw_file: Path, content: str) -> None:
    pw_file.parent.mkdir(parents=True)
    pw_file.write_text(content, encoding="utf-8")
    assert password.stored_hash() == ""
    assert password.check_password("old", legacy="old")


@pytest.mark.parametrize("stored", ["", "md5$1$a$b", "pbkdf2_sha256$x$a$b", "pbkdf2_sha256$1$!!$??", "a$b"])
def test_malformed_hash_never_verifies(stored: str) -> None:
    assert not password.verify_hash("anything", stored)


def test_cli_set_prompts_twice(pw_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["4321", "4321"])
    monkeypatch.setattr(password.getpass, "getpass", lambda prompt="": next(answers))
    assert password.main(["set"]) == 0
    assert password.check_password("4321")


def test_cli_set_mismatch_changes_nothing(pw_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["4321", "4322"])
    monkeypatch.setattr(password.getpass, "getpass", lambda prompt="": next(answers))
    assert password.main(["set"]) == 1
    assert not pw_file.exists()


def test_cli_set_from_stdin(pw_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("long pass phrase\n"))
    assert password.main(["set", "--stdin"]) == 0
    assert password.check_password("long pass phrase")
    assert "long pass phrase" not in capsys.readouterr().out


def test_cli_set_empty_stdin_is_refused(pw_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert password.main(["set", "--stdin"]) == 1
    assert not pw_file.exists()


def test_cli_status(pw_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert password.main(["status"]) == 0
    assert "not stored" in capsys.readouterr().out
    password.set_password("1234")
    assert password.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "stored" in out and "not stored" not in out and "1234" not in out


def test_password_never_logged(pw_file: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    password.set_password("s3cret-fixture")
    password.check_password("s3cret-fixture")
    assert "s3cret-fixture" not in caplog.text
