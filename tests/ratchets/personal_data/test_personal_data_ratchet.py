"""Tests for the personal data ratchet.

Three layers, mirroring `test_port_host_ratchet.py`:

1. **Rules** on in-memory files. Every term, handle, email and path here is
   invented, and the leaking strings are assembled at run time, so this module
   is not itself a finding.
2. **Ratchet behaviour** on throwaway git repos with a throwaway term list:
   every mode, a planted term, the no-list case and "not confirmed". The
   machine's real term list is never read.
3. **Self-adoption**: this repo's own declaration, catalogue entry and gate wiring.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts import personal_data_ratchet as pd
from src.no_window import NO_WINDOW
from tests._git_repo import git, write
from tests._ratchet_not_confirmed import assert_unreadable_file_not_confirmed, git_failure_test

REPO_ROOT = Path(__file__).resolve().parents[3]

BS = "\\"
AT = "@"
HANDLE = "zq-invented-owner"
TERM_LIST = f"""\
names   = ["Quillon Vantablatt"]
handles = ["qvantablatt"]
emails  = ["quillon{AT}vantablatt.example"]
domains = ["vantablatt.example"]
apps    = ["flumewidget"]
"""


def drive(*parts: str, sep: str = BS, letter: str = "C") -> str:
    return letter + ":" + sep + sep.join(parts)


def posix(*parts: str) -> str:
    return "/" + "/".join(parts)


def mail(local: str = "jo", domain: str = "corp-mail.io") -> str:
    return local + AT + domain


def terms(handle: str | None = HANDLE, **by_rule: str) -> pd.Terms:
    return pd.Terms({rule.replace("_", "-"): pd._term_pattern((term,)) for rule, term in by_rule.items()},
                    pd._handle_pattern((handle,)) if handle else None)


def rules(src: str, path: str = "src/app.py", known: pd.Terms | None = None) -> list[str]:
    """`rule:line` of each finding left after exemptions in one file."""
    return [f"{rule}:{line}" for line, rule in pd.scan_source(src, path, known or terms()).findings]


# ------------------------------------------------- user-path

@pytest.mark.parametrize("path", [
    drive("Users", "alice", "notes.txt"),
    drive("Users", "alice", sep="/"),
    drive("Users", "alice", sep=BS + BS),
    drive("users", "bob"),
    drive("automation", "some-repo", letter="E"),
    drive("projects", letter="D"),
    drive("dev", "thing", letter="d", sep="/"),
    posix("home", "alice", "src"),
    posix("Users", "alice"),
    posix("c", "Users", "alice"),
    posix("mnt", "e", "automation", "some-repo"),
    "file://" + posix("home", "alice"),
])
def test_an_absolute_user_or_checkout_path_is_a_hit(path: str) -> None:
    assert rules(f"see {path} here\n", "docs/a.md") == ["user-path:1"]


@pytest.mark.parametrize("placeholder", ["<root>", "<you>", "me", "you", "sample"])
@pytest.mark.parametrize("make", [
    lambda who: drive("Users", who, "app"),
    lambda who: drive("automation", who, letter="E"),
    lambda who: posix("home", who, "app"),
    lambda who: posix("Users", who),
])
def test_each_allowed_placeholder_is_clean(placeholder: str, make: Callable[[str], str]) -> None:
    assert rules(f"see {make(placeholder)}.\n", "docs/a.md") == []


@pytest.mark.parametrize("line", [
    drive("Users", "%USERNAME%", "app"), posix("home", "$USER", "x"), posix("home", "{user}", "x"),
    drive("Users", "..."), drive("Users"), "open <root>" + BS + "some-repo", "https://host.io" + posix("home", "page"),
    "{base}" + posix("home", "page"), "app" + posix("home", "page"), drive("Windows", "System32"),
    drive("automation-x", "y"), "write to /dev/null",
])
def test_generic_interpolated_and_url_paths_are_clean(line: str) -> None:
    assert rules(line + "\n", "docs/a.md") == []


# ------------------------------------------------- personal-email

@pytest.mark.parametrize("address", [mail(), mail("first.last+tag", "sub.corp-mail.co.uk"), mail("x", "host.local")])
def test_an_email_outside_the_reserved_domains_is_a_hit(address: str) -> None:
    assert rules(f"write to {address}: thanks\n", "docs/a.md") == ["personal-email:1"]


@pytest.mark.parametrize("line", [
    mail("a", "example.com"), mail("a", "mail.example.org"), mail("a", "example.net"), mail("a", "corp.example"),
    mail("a", "corp.test"), mail("a", "corp.invalid"), mail("git", "github.com") + ":o/r.git",
    "ssh " + mail("pi", "box.lan") + ":/srv", "icon" + AT + "2x.png", "uses: actions/checkout" + AT + "v6",
    "npm i " + AT + "types/node", "pkg" + AT + "1.2.3", "x = '" + BS + "n" + AT + "pytest.mark.win'",
])
def test_reserved_domains_and_lookalikes_are_not_emails(line: str) -> None:
    assert rules(line + "\n", "docs/a.md") == []


# ------------------------------------------------- handle-default

@pytest.mark.parametrize(("path", "line"), [
    ("src/app.py", f'OWNER = "{HANDLE}"'),
    ("src/app.py", f'repo = os.environ.get("REPO", "{HANDLE}/thing")'),
    ("scripts/x.sh", 'REPO="${REPO:-' + HANDLE + '/thing}"'),
    ("scripts/x.ps1", f"$Owner = '{HANDLE}'"),
    (".github/workflows/x.yml", f"if: github.repository == '{HANDLE}/thing'"),
    ("config/app.sample.json", f'{{"owner": "{HANDLE}"}}'),
    ("tray.bat.template", f'set "OWNER={HANDLE}"'),
    (".env.example", f"OWNER={HANDLE}"),
])
def test_the_handle_used_as_a_value_is_a_hit(path: str, line: str) -> None:
    assert rules(line + "\n", path) == ["handle-default:1"]


@pytest.mark.parametrize(("path", "line"), [
    ("src/app.py", f'URL = "https://github.com/{HANDLE}/thing.git"'),
    ("src/app.py", f'REMOTE = "{mail("git", "github.com")}:{HANDLE}/thing.git"'),
    ("src/app.py", f'SEE = "{HANDLE}/thing' + '#12"'),
    ("src/app.py", f"# owned by {HANDLE}"),
    ("src/app.py", f'"""Maintained by {HANDLE}."""'),
    ("scripts/x.ps1", f"<#\n {HANDLE}\n#>"),
    ("README.md", f"owner: {HANDLE}"),
    ("src/app.py", f'OTHER = "{HANDLE}-fork"'),
])
def test_urls_issue_links_comments_and_prose_are_not_handle_defaults(path: str, line: str) -> None:
    assert rules(line + "\n", path) == []


@pytest.mark.parametrize(("url", "owner"), [
    ("https://github.com/Some-Owner/repo.git", "Some-Owner"),
    (mail("git", "github.com") + ":Some-Owner/repo.git", "Some-Owner"),
    ("ssh://" + mail("git", "github.com") + "/Some-Owner/repo", "Some-Owner"),
    (None, None),
])
def test_the_handle_comes_from_the_origin_remote(tmp_path: Path, url: str | None, owner: str | None) -> None:
    git(tmp_path, "init", "-q")
    if url:
        git(tmp_path, "remote", "add", "origin", url)
    assert pd.origin_owner(tmp_path) == owner


# ------------------------------------------------- term rules and exemptions

@pytest.mark.parametrize(("rule", "term", "line"), [
    ("term-name", "Quillon Vantablatt", "Written by quillon vantablatt."),
    ("term-handle", "qvantablatt", "cc qvantablatt"),
    ("term-email", mail("q", "vantablatt.example"), "to " + mail("q", "vantablatt.example")),
    ("term-domain", "vantablatt.example", "see https://www.vantablatt.example/x"),
    ("term-app", "flumewidget", "FLUMEWIDGET_DIR = 1"),
])
def test_each_term_rule_matches_its_term(rule: str, term: str, line: str) -> None:
    known = terms(handle=None, **{rule.replace("-", "_"): term})
    assert rules(line + "\n", "docs/a.md", known) == [f"{rule}:1"]


def test_a_term_inside_a_longer_word_is_not_a_hit() -> None:
    assert rules("flumewidgets and superflumewidget\n", "docs/a.md", terms(term_app="flumewidget")) == []


def test_an_exemption_with_a_reason_on_the_line_or_above_keeps_the_hit() -> None:
    on_line = f"TO = '{mail()}'  # personal-email-exempt: the vendor's public support address\n"
    above = f"<!-- user-path-exempt: the vendor's fixed install path -->\n{drive('Users', 'svc')}\n"
    assert rules(on_line) == []
    assert rules(above, "docs/a.md") == []
    assert pd.scan_source(above, "docs/a.md", terms()).exempted == [(2, "user-path", "the vendor's fixed install path")]


def test_an_exemption_covers_only_the_rule_it_names() -> None:
    line = f"{drive('Users', 'svc')} {mail()}  # user-path-exempt: fixed path\n"
    assert rules(line, "docs/a.md") == ["personal-email:1"]


def test_a_marker_with_no_reason_exempts_nothing_and_is_itself_a_hit() -> None:
    assert sorted(rules(f"TO = '{mail()}'  # personal-email-exempt\n")) == ["bare-exempt:1", "personal-email:1"]


# ------------------------------------------------- config and term list

def test_absent_or_disabled_table_is_not_enabled_and_the_default_runs_every_rule() -> None:
    assert pd.parse_config("") is None
    assert pd.parse_config("[personal_data_ratchet]\nenabled = false\n") is None
    cfg = pd.parse_config("[personal_data_ratchet]\nenabled = true\n")
    assert cfg == pd.Config(pd.DEFAULT_BASELINE, pd.RULES, ())


@pytest.mark.parametrize("body", [
    "enabled = 'yes'", "enabled = true\ntypo = 1", "enabled = true\nrules = ['nope']",
    "enabled = true\nexclude = 'x'", "enabled = true\nbaseline = ''",
])
def test_a_malformed_table_is_a_config_error(body: str) -> None:
    with pytest.raises(pd.ConfigError):
        pd.parse_config(f"[personal_data_ratchet]\n{body}\n")


# ------------------------------------------------- ratchet on a git repo

def run_mode(repo: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return pd.run(repo, init=init, update=update, allow_additions=allow)


@pytest.fixture()
def term_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "terms.toml"
    path.write_text(TERM_LIST, encoding="utf-8")
    monkeypatch.setenv(pd.TERMS_ENV, str(path))
    return path


@pytest.fixture()
def repo(tmp_path: Path, term_list: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "remote", "add", "origin", f"https://github.com/{HANDLE}/thing.git")
    write(root, ".fleet.toml", "[personal_data_ratchet]\nenabled = true\n")
    write(root, "src/app.py", "NAME = 'neutral'\n")
    return root


def baseline(repo: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = json.loads((repo / pd.DEFAULT_BASELINE).read_text(encoding="utf-8"))["entries"]
    return entries


def test_a_planted_term_fails_and_passes_once_removed_without_being_echoed(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_mode(repo, init=True) == pd.EXIT_PASS
    write(repo, "docs/flumewidget.md", "The flumewidget app by Quillon Vantablatt.\n")
    capsys.readouterr()
    assert run_mode(repo) == pd.EXIT_RISE
    out = capsys.readouterr().out
    assert "docs/***.md:1: [term-app]" in out and "docs/***.md:1: [term-name]" in out
    assert "flumewidget" not in out.lower() and "quillon" not in out.lower()
    write(repo, "docs/flumewidget.md", "The sample app.\n")
    assert run_mode(repo) == pd.EXIT_PASS


def test_pattern_findings_are_not_echoed_either(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/app.py", f"A = r'{drive('Users', 'alice')}'\nB = '{mail()}'\nC = '{HANDLE}'\n")
    capsys.readouterr()
    assert run_mode(repo) == pd.EXIT_RISE
    out = capsys.readouterr().out
    assert all(f"src/app.py:{n}: [{r}]" in out for n, r in
               ((1, "user-path"), (2, "personal-email"), (3, "handle-default")))
    assert "alice" not in out and "corp-mail" not in out and HANDLE not in out


def test_the_baseline_only_shrinks_and_holds_no_matched_text(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "src/app.py", f"B = '{mail()}'\n")
    assert run_mode(repo, init=True) == pd.EXIT_PASS
    assert baseline(repo) == [{"key": "src/app.py", "counts": {"personal-email": 1}}]
    assert run_mode(repo) == pd.EXIT_PASS
    write(repo, "src/other.py", "A = 'flumewidget'\n")
    assert run_mode(repo, update=True) == pd.EXIT_RISE
    assert run_mode(repo, update=True, allow=True) == pd.EXIT_PASS
    write(repo, "src/app.py", "B = ''\n")
    capsys.readouterr()
    assert run_mode(repo) == pd.EXIT_PASS
    assert "1 baselined hit(s) are gone" in capsys.readouterr().out
    assert run_mode(repo, update=True) == pd.EXIT_PASS
    assert [e["key"] for e in baseline(repo)] == ["src/other.py"]
    assert run_mode(repo, init=True) == pd.EXIT_CONFIG


def test_with_no_term_list_term_rules_are_unknown_and_pattern_rules_still_enforced(
    repo: Path, term_list: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_mode(repo, init=True)
    term_list.unlink()
    capsys.readouterr()
    assert run_mode(repo) == pd.EXIT_NOT_CONFIRMED
    out = capsys.readouterr().out
    assert all(f"{rule}: unknown -- no term list" in out for rule in pd.TERM_KEYS)
    assert "NOT CONFIRMED" in out and "PASS" not in out
    assert str(term_list) not in out, "the term list's path can carry a user name"
    write(repo, "src/app.py", f"B = '{mail()}'\n")
    assert run_mode(repo) == pd.EXIT_RISE
    assert "src/app.py:1: [personal-email]" in capsys.readouterr().out


def test_a_rewrite_without_the_term_list_keeps_the_term_entries(repo: Path, term_list: Path) -> None:
    write(repo, "src/app.py", f"A = 'flumewidget'\nB = '{mail()}'\n")
    run_mode(repo, init=True)
    term_list.unlink()
    write(repo, "src/app.py", "A = 'flumewidget'\n")
    assert run_mode(repo, update=True) == pd.EXIT_NOT_CONFIRMED
    assert baseline(repo) == [{"key": "src/app.py", "counts": {"term-app": 1}}]


def test_a_missing_key_is_unknown_and_an_empty_list_is_a_declared_none(
    repo: Path, term_list: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    term_list.write_text("names = []\nhandles = []\nemails = []\ndomains = []\n", encoding="utf-8")
    assert run_mode(repo, init=True) == pd.EXIT_NOT_CONFIRMED
    out = capsys.readouterr().out
    assert "term-app: unknown" in out and "term-name: unknown" not in out
    term_list.write_text(term_list.read_text(encoding="utf-8") + "apps = []\n", encoding="utf-8")
    assert run_mode(repo) == pd.EXIT_PASS


def test_narrowed_rules_are_reported_off_and_need_no_term_list(
    repo: Path, term_list: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    term_list.unlink()
    write(repo, ".fleet.toml", "[personal_data_ratchet]\nenabled = true\nrules = ['user-path', 'personal-email']\n")
    assert run_mode(repo, init=True) == pd.EXIT_PASS
    assert run_mode(repo) == pd.EXIT_PASS
    assert "OFF (not listed in `rules`): handle-default, term-name" in capsys.readouterr().out


def test_without_an_origin_or_listed_handle_handle_default_is_unknown(
    repo: Path, term_list: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git(repo, "remote", "remove", "origin")
    term_list.write_text("names = []\nhandles = []\nemails = []\ndomains = []\napps = []\n", encoding="utf-8")
    assert run_mode(repo, init=True) == pd.EXIT_NOT_CONFIRMED
    assert "handle-default: unknown" in capsys.readouterr().out


@pytest.mark.parametrize("body", [
    "flumewidget = 1\n", "apps = 'flumewidget'\n", "apps = ['ab']\n", "apps = [flumewidget\n", "extra = []\n",
])
def test_a_malformed_term_list_is_a_config_error_that_quotes_none_of_it(
    repo: Path, term_list: Path, capsys: pytest.CaptureFixture[str], body: str
) -> None:
    term_list.write_text(body, encoding="utf-8")
    assert run_mode(repo, init=True) == pd.EXIT_CONFIG
    assert "flumewidget" not in capsys.readouterr().out


def test_a_term_list_git_would_commit_is_refused(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "terms.toml", TERM_LIST, track=False)
    monkeypatch.setenv(pd.TERMS_ENV, str(repo / "terms.toml"))
    assert run_mode(repo, init=True) == pd.EXIT_CONFIG
    assert "move it outside the repository" in capsys.readouterr().out
    assert not (repo / pd.DEFAULT_BASELINE).exists()


def test_vendored_copies_excludes_ignored_files_and_binaries_are_not_read(repo: Path) -> None:
    run_mode(repo, init=True)
    leak = f"{mail()}\n"
    write(repo, ".gitignore", "local.json\n")
    write(repo, "local.json", leak, track=False)
    write(repo, "app/_vendored/x.js", leak)
    write(repo, "third_party/x.js", leak)
    (repo / "icon.png").write_bytes(b"\x89PNG\0\0" + leak.encode())
    write(repo, ".fleet.toml", "[personal_data_ratchet]\nenabled = true\nexclude = ['third_party/**']\n"
                               "[vendored]\nx = { src = 'app/v', dest = 'app/_vendored' }\n")
    assert run_mode(repo) == pd.EXIT_PASS


def test_a_utf16_file_is_read(repo: Path) -> None:
    run_mode(repo, init=True)
    (repo / "out.txt").write_bytes(f"{mail()}\n".encode("utf-16"))
    assert run_mode(repo) == pd.EXIT_RISE


@pytest.mark.parametrize(("rel", "body", "says"), [
    ("src/bad.py", b"def f(:\n", "cannot be parsed"),
    ("src/latin.py", b"x = '\xe9'\n", "is not UTF-8"),
])
def test_a_file_it_cannot_read_through_is_not_confirmed(
    repo: Path, rel: str, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_unreadable_file_not_confirmed(pd, run_mode, repo, rel, body, says, capsys)


test_git_that_cannot_list_the_tree_is_not_confirmed = git_failure_test(pd, run_mode)


def test_a_not_confirmed_path_masks_a_listed_term(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "flumewidget.txt").write_bytes("é".encode("latin-1"))
    assert run_mode(repo, init=True) == pd.EXIT_NOT_CONFIRMED
    out = capsys.readouterr().out
    assert "NOT CONFIRMED: ***.txt" in out and "flumewidget" not in out


def test_the_script_runs_standalone(repo: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-P", str(REPO_ROOT / "scripts" / "personal_data_ratchet.py"), "--root", str(repo), "--init"],
        capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------- self-adoption

def test_the_scaffold_enables_the_stage_with_a_baseline() -> None:
    cfg, _ = pd.load_config(REPO_ROOT)
    assert cfg is not None and (REPO_ROOT / cfg.baseline).is_file()


def test_gate_runs_the_stage_after_the_clean_tree_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (text.index(s) for s in (
        'Invoke-Stage "clean tree ratchet"', 'Invoke-Stage "personal data ratchet"', 'Invoke-Stage "mypy'))
    assert before < stage < mypy


def test_the_script_is_catalogued() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["personal_data_ratchet"]["src"] == "scripts/personal_data_ratchet.py"


def test_every_rule_is_documented() -> None:
    doc = (REPO_ROOT / "docs" / "personal-data-ratchet.md").read_text(encoding="utf-8")
    for rule in pd.RULES:
        assert f"`{rule}`" in doc and f"`{rule}`" in (pd.__doc__ or ""), rule
