"""Tests for the port host ratchet.

Three layers, mirroring `test_windows_only_ratchet.py`:

1. **Rules** on in-memory files: each rule fails by name on a planted literal
   and passes once the value comes from config, sits in prose, or is exempted.
   The reference cases are the launcher defaults a side-by-side machine had to
   edit by hand (a `.bat` port, a session-host port, a tray reclaim list).
2. **Ratchet behaviour** on throwaway git repos: every mode, a rise, the
   resolver, sample, test and vendored perimeter, and "not confirmed".
3. **Self-adoption**: this repo's own declaration, catalogue entry and gate wiring.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import port_host_ratchet as ph
from src.no_window import NO_WINDOW
from tests._git_repo import git, write
from tests._ratchet_not_confirmed import assert_unreadable_file_not_confirmed, git_failure_test

REPO_ROOT = Path(__file__).resolve().parents[2]


def hits(src: str, path: str = "src/app.py") -> list[str]:
    """`rule:line` of each finding left after prose and exemptions in one file."""
    return [f"{rule}:{line}" for line, rule, _ in ph.scan_source(src, path).findings]


# ------------------------------------------------- rules

@pytest.mark.parametrize(("path", "line"), [
    ("webapp.bat", 'set "PORT=8465"'),
    ("app/server.py", "DEFAULT_PORT = 8466"),
    ("app/manager.py", "port: int = 8445"),
    ("src/notify.py", 'BASE = "http://127.0.0.1:8000"'),
    ("src/notify.py", 'url = f"https://{host}:8445/api"'),
    ("scripts/start.ps1", 'reclaim -VenvDir $v -Ports "8465,8466"'),
    ("scripts/start.ps1", "$webappPort = 8445"),
    ("scripts/run.sh", "exec app --port 8130"),
    ("scripts/run.cmd", "curl http://%HOST%:8445/healthz"),
    ("static/app.js", 'const cfg = {"port": 8000};'),
    ("static/app.js", "fetch('http://localhost:8501/x')"),
])
def test_a_port_literal_is_a_hit(path: str, line: str) -> None:
    assert hits(line + "\n", path) == ["port-literal:1"]


@pytest.mark.parametrize("line", [
    "report = 8000", "export_count = 12", "port = cfg.port", "port = 0", "sport = 4000",
    'version = "1.2.3.4"', "PORT = int(os.environ['PORT'])", "ports = []",
])
def test_names_and_values_that_are_not_port_literals_are_clean(line: str) -> None:
    assert hits(line + "\n") == []


@pytest.mark.parametrize("line", [
    'HUB = "192.168.1.20"', 'peer = "10.0.4.7"', 'tail = "100.101.102.103"', 'NAS = "nas.tail1234.ts.net"',
    "bind = '172.20.0.5'",
])
def test_a_machine_local_host_is_a_hit(line: str) -> None:
    assert hits(line + "\n") == ["host-literal:1"]


@pytest.mark.parametrize("line", [
    'CGNAT = ipaddress.ip_network("100.64.0.0/10")', 'PUBLIC = "8.8.8.8"', 'LOOP = "127.0.0.1"',
    'nets = ("10.0.0.0/8", "192.168.0.0/16")', 'bad = "10.300.1.1"', 'v = "110.64.1.1"',
])
def test_networks_public_and_loopback_addresses_are_not_host_literals(line: str) -> None:
    assert hits(line + "\n") == []


def test_a_host_with_a_port_counts_once_per_rule() -> None:
    assert sorted(hits('URL = "http://192.168.1.20:8445"\n')) == ["host-literal:1", "port-literal:1"]


@pytest.mark.parametrize(("path", "src"), [
    ("src/app.py", '"""Talks to the hub at http://127.0.0.1:8000."""\n\ndef f():\n    """Port 8445 by default."""\n'),
    ("src/app.py", "# the hub listens on 127.0.0.1:8000\n"),
    ("webapp.bat", "REM default PORT=8465\n:: or 8466\n"),
    ("scripts/start.ps1", '<#\n  reclaim -Ports "8465,8466"\n#>\n$x = 1\n'),
    ("static/app.js", "/*\n * localhost:8501\n */\n"),
])
def test_comments_and_docstrings_are_prose(path: str, src: str) -> None:
    assert hits(src, path) == []


def test_code_after_a_closed_block_comment_is_read() -> None:
    assert hits('<# help #>\n$port = 8445\n', "scripts/start.ps1") == ["port-literal:2"]


def test_an_exemption_with_a_reason_on_the_line_or_above_keeps_the_hit() -> None:
    on_line = 'PROBE = ("10.255.255.255", 9)  # port-host-exempt: an unroutable address to read the LAN route\n'
    above = "# port-host-exempt: the documented default of the external hub\nHUB = 'http://127.0.0.1:8000'\n"
    assert hits(on_line) == [] and hits(above) == []
    scan = ph.scan_source(above, "src/app.py")
    assert scan.exempted == [(2, "port-literal", "the documented default of the external hub")]


def test_an_exemption_two_lines_up_or_above_code_does_not_reach() -> None:
    src = "# port-host-exempt: too far\nx = 1\nPORT = 8445\n"
    assert hits(src) == ["port-literal:3"]


def test_a_marker_with_no_reason_exempts_nothing_and_is_itself_a_hit() -> None:
    assert sorted(hits("PORT = 8445  # port-host-exempt\n")) == ["bare-exempt:1", "port-literal:1"]


# ------------------------------------------------- perimeter

@pytest.mark.parametrize(("path", "scanned"), [
    ("src/app.py", True), ("webapp.bat", True), ("scripts/x.ps1", True), ("static/app.mjs", True),
    ("config/config.json", False), ("README.md", False), ("config/ports.sample.py", False),
    ("scripts/start.example.ps1", False), ("tests/test_app.py", False), ("app/tests/helper.py", False),
    ("static/app.test.js", False), ("src/config.py", False), (".venv/lib/x.py", False),
])
def test_the_perimeter_is_code_outside_resolvers_samples_and_tests(path: str, scanned: bool) -> None:
    cfg = ph.Config(ph.DEFAULT_BASELINE, ph.RULES, resolvers=("src/config.py",))
    assert ph.in_scope(path, cfg, ()) is scanned


def test_include_tests_reads_tests_and_vendored_dests_are_never_read() -> None:
    cfg = ph.Config(ph.DEFAULT_BASELINE, ph.RULES, include_tests=True)
    assert ph.in_scope("tests/test_app.py", cfg, ())
    assert not ph.in_scope("app/_vendored/nav/x.js", cfg, ("app/_vendored",))


# ------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert ph.parse_config("") is None
    assert ph.parse_config("[port_host_ratchet]\nenabled = false\n") is None


def test_enabled_table_defaults() -> None:
    cfg = ph.parse_config("[port_host_ratchet]\nenabled = true\n")
    assert cfg == ph.Config(ph.DEFAULT_BASELINE, ph.RULES, (), False, ())


@pytest.mark.parametrize("body", [
    "enabled = 'yes'", "enabled = true\ntypo = 1", "enabled = true\nrules = ['nope']",
    "enabled = true\nresolvers = 'src/config.py'", "enabled = true\ninclude_tests = 1",
    "enabled = true\nbaseline = ''",
])
def test_a_malformed_table_is_a_config_error(body: str) -> None:
    with pytest.raises(ph.ConfigError):
        ph.parse_config(f"[port_host_ratchet]\n{body}\n")


# ------------------------------------------------- ratchet on a git repo

def run_mode(repo: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return ph.run(repo, init=init, update=update, allow_additions=allow)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    write(tmp_path, ".fleet.toml", "[port_host_ratchet]\nenabled = true\nresolvers = ['src/config.py']\n")
    write(tmp_path, "src/config.py", "DEFAULT_PORT = 8445\n")
    write(tmp_path, "src/app.py", "from src.config import DEFAULT_PORT\n")
    return tmp_path


def test_init_then_a_new_literal_rises_and_exits_one(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo, init=True) == ph.EXIT_PASS
    assert '"entries": []' in (repo / ph.DEFAULT_BASELINE).read_text(encoding="utf-8")
    assert run_mode(repo) == ph.EXIT_PASS
    write(repo, "webapp.bat", '@echo off\nset "PORT=8445"\n')
    assert run_mode(repo) == ph.EXIT_RISE
    assert "webapp.bat:2: [port-literal]" in capsys.readouterr().out
    write(repo, "webapp.bat", "@echo off\nfor /f %%p in ('python -m src.config port') do set PORT=%%p\n")
    assert run_mode(repo) == ph.EXIT_PASS


def test_existing_debt_passes_and_a_fix_hints_the_shrink(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "src/app.py", "PORT = 8445\n")
    assert run_mode(repo, init=True) == ph.EXIT_PASS
    write(repo, "src/app.py", "from src.config import DEFAULT_PORT as PORT\n")
    capsys.readouterr()
    assert run_mode(repo) == ph.EXIT_PASS
    assert "1 baselined hit(s) are gone" in capsys.readouterr().out
    assert run_mode(repo, update=True) == ph.EXIT_PASS
    assert '"entries": []' in (repo / ph.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_update_refuses_additions_unless_allowed(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/app.py", "PORT = 8445\n")
    assert run_mode(repo, update=True) == ph.EXIT_RISE
    assert run_mode(repo, update=True, allow=True) == ph.EXIT_PASS
    assert run_mode(repo) == ph.EXIT_PASS


def test_init_never_overwrites_and_a_missing_baseline_fails(repo: Path) -> None:
    assert run_mode(repo) == ph.EXIT_RISE
    run_mode(repo, init=True)
    assert run_mode(repo, init=True) == ph.EXIT_CONFIG


def test_resolver_samples_tests_excludes_and_vendored_copies_are_not_read(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "config/ports.sample.py", "PORT = 8445\n")
    write(repo, "tests/test_boot.py", "PORT = 18445\n")
    write(repo, "scripts/bench/probe.py", "BASE = 'http://127.0.0.1:8445'\n")
    write(repo, "app/_vendored/x.js", "fetch('http://localhost:8445')\n")
    write(repo, ".fleet.toml", "[port_host_ratchet]\nenabled = true\nresolvers = ['src/config.py']\n"
                               "exclude = ['scripts/bench/**']\n"
                               "[vendored]\nx = { src = 'app/v', dest = 'app/_vendored' }\n")
    assert run_mode(repo) == ph.EXIT_PASS


@pytest.mark.parametrize(("rel", "body", "says"), [
    ("src/bad.py", b"def f(:\n", "cannot be parsed"),
    ("src/latin.py", b"x = '\xe9'\n", "is not UTF-8"),
])
def test_a_file_it_cannot_read_through_is_not_confirmed(
    repo: Path, rel: str, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_unreadable_file_not_confirmed(ph, run_mode, repo, rel, body, says, capsys)


test_git_that_cannot_list_the_tree_is_not_confirmed = git_failure_test(ph, run_mode)


def test_the_script_runs_standalone(repo: Path) -> None:
    proc = subprocess.run([sys.executable, "-P", str(REPO_ROOT / "scripts" / "port_host_ratchet.py"), "--root",
                           str(repo), "--init"], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------- self-adoption

def test_the_scaffold_enables_the_stage_with_a_baseline() -> None:
    cfg, _ = ph.load_config(REPO_ROOT)
    assert cfg is not None and (REPO_ROOT / cfg.baseline).is_file()


def test_gate_runs_the_stage_after_the_windows_only_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (text.index(s) for s in (
        'Invoke-Stage "windows only ratchet"', 'Invoke-Stage "port host ratchet"', 'Invoke-Stage "mypy'))
    assert before < stage < mypy


def test_the_script_is_catalogued() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["port_host_ratchet"]["src"] == "scripts/port_host_ratchet.py"


def test_every_rule_is_documented() -> None:
    doc = (REPO_ROOT / "docs" / "port-host-ratchet.md").read_text(encoding="utf-8")
    for rule in ph.RULES:
        assert f"`{rule}`" in doc and f"`{rule}`" in (ph.__doc__ or ""), rule
