"""Tests for the request budget ratchet.

Three layers, mirroring `test_usage_track_ratchet.py`:

1. **Rules** on in-memory sources: each rule fails by name on a planted
   violation and passes on clean code, plus the exemption marker, a bare marker,
   and the declarations each rule honours (`activeWhile`, declared loops, the
   stat cache).
2. **Ratchet behaviour** on throwaway git repos: every mode, a rise, the
   repo-level middleware rule, vendored copies, and the "not confirmed" exit for
   anything that cannot be read through.
3. **Self-adoption**: this repo's own declaration, catalogue entry and gate wiring.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import request_budget_ratchet as rb
from scripts import request_budget_scan as scan
from src.no_window import NO_WINDOW
from tests._git_repo import git, write
from tests._ratchet_not_confirmed import assert_unreadable_file_not_confirmed, git_failure_test

REPO_ROOT = Path(__file__).resolve().parents[2]


def js(src: str, wrappers: tuple[str, ...] = (), fetchers: tuple[str, ...] = ()) -> list[str]:
    """`rule:line` of each finding left after exemptions in one JS source."""
    kept, _ = scan.apply_exemptions(src, scan.scan_js(src, "app.js", wrappers, fetchers))
    return [f"{rule}:{line}" for line, rule, _ in kept]


def py(src: str, *, declared: dict[str, float] | None = None, handler: bool = False,
       stat_cache: tuple[str, ...] = ()) -> list[str]:
    facts = scan.scan_python(src, "src/x.py", declared=declared or {}, handler=handler, stat_cache=stat_cache)
    kept, _ = scan.apply_exemptions(src, facts.findings)
    return [f"{rule}:{line}" for line, rule, _ in kept]


# ------------------------------------------------- RB1 fixed-rate-poll

def test_rb1_a_set_interval_that_fetches_is_a_hit() -> None:
    assert js("setInterval(() => fetch('/api/board'), 5000);\n") == ["fixed-rate-poll:1"]


def test_rb1_reaches_the_server_through_a_named_function() -> None:
    src = "function load() { return fetch('/api/x'); }\nfunction tick() { load(); }\nwindow.setInterval(tick, 5000);\n"
    assert js(src) == ["fixed-rate-poll:3"]


def test_rb1_a_call_this_file_does_not_define_cannot_be_ruled_out() -> None:
    assert js("import { refresh } from './api.js';\nsetInterval(refresh, 5000);\n") == ["fixed-rate-poll:2"]


def test_rb1_a_declared_wrapper_and_a_declared_fetcher_are_read() -> None:
    assert js("createPoller(() => apiGet('/x'), 5000);\n", ("createPoller",), ("apiGet",)) == ["fixed-rate-poll:1"]


def test_rb1_clean_a_pure_clock_and_the_poll_helper() -> None:
    clock = "function paint() { el.textContent = String(new Date().getSeconds()); }\nsetInterval(paint, 1000);\n"
    assert js(clock) == []
    assert js("import { startPoll } from './poll.js';\nstartPoll(() => fetch('/api/x'), 5000);\n") == []


def test_rb1_fetch_inside_a_string_or_comment_is_not_code() -> None:
    assert js("// setInterval(() => fetch('/x'), 1)\nconst s = 'setInterval(() => fetch(1), 1)';\n") == []


def test_rb1_an_exempt_marker_with_a_reason_keeps_the_hit_out() -> None:
    src = "// request-budget-exempt: a ticking clock whose callback is passed in\nsetInterval(paint, 1000);\n"
    assert js(src) == []


# ------------------------------------------------- JS masker: nested templates

def _blanked(src: str) -> str:
    return scan.mask_js(src, "p")


def test_mask_nested_template_in_a_substitution_is_fully_blanked() -> None:
    src = "const a = `x ${b ? `: ${c}` : ''} y`;\nfoo(`<use/>`);\n"
    out = _blanked(src)
    assert out == "const a = `" + " " * len("x ${b ? `: ${c}` : ''} y") + "`;\nfoo(`" + " " * 6 + "`);\n"
    assert len(out) == len(src)


def test_mask_keeps_offsets_and_newlines_through_nested_templates() -> None:
    src = "x = `a ${`b\n${`c`}`} d\n`;\ny = 1;\n"
    out = _blanked(src)
    assert len(out) == len(src)
    assert [i for i, ch in enumerate(out) if ch == "\n"] == [i for i, ch in enumerate(src) if ch == "\n"]
    assert out.endswith("`;\ny = 1;\n")
    assert "b" not in out and "c" not in out


def test_mask_a_brace_inside_a_nested_string_does_not_close_the_substitution() -> None:
    template = "`${ f('}') + `${ \"}\" }` }`"
    out = _blanked(f"a = {template}; setInterval(g, 1);\n")
    assert out == "a = `" + " " * (len(template) - 2) + "`; setInterval(g, 1);\n"


def test_mask_a_comment_or_regex_inside_a_substitution_is_not_code() -> None:
    src = "a = `${ /* } ` */ x }`; b = `${ y // } `\n}`; z();\n"
    out = _blanked(src)
    assert "z();" in out and out.count("`") == 4


def test_mask_a_planted_unclosed_nested_template_is_not_confirmed() -> None:
    with pytest.raises(scan.NotConfirmed):
        _blanked("a = `x ${ b ? `: ${c}` : '' y;\nfoo();\n")
    with pytest.raises(scan.NotConfirmed):
        _blanked("a = `x ${ `never closes ${c} };\n")


# ------------------------------------------------------- RB2 poll-floor

def test_rb2_a_fast_start_poll_is_a_hit_and_active_while_clears_it() -> None:
    assert js("startPoll(read, 1000);\n") == ["poll-floor:1"]
    assert js("startPoll(read, 1000, { activeWhile: () => job.running });\n") == []


def test_rb2_reads_products_and_constants() -> None:
    assert js("const FAST = 1 * 500;\nstartPoll(read, FAST);\n") == ["poll-floor:2"]
    assert js("const SLOW = 5 * 1_000;\nstartPoll(read, SLOW);\n") == []


def test_rb2_a_fast_fixed_rate_fetch_poll_breaks_both_rules() -> None:
    assert js("setInterval(() => fetch('/x'), 500);\n") == ["fixed-rate-poll:1", "poll-floor:1"]


def test_rb2_clean_an_interval_it_cannot_read_is_not_judged() -> None:
    assert js("startPoll(read, settings.pollMs);\n") == []


# --------------------------------------------------- RB3 unwatched-loop

LOOP = "import time\n\ndef run():\n    while True:\n        work()\n        time.sleep({})\n"


def test_rb3_a_loop_under_the_floor_is_a_hit() -> None:
    assert py(LOOP.format("1")) == ["unwatched-loop:4"]


def test_rb3_an_interval_it_cannot_read_is_a_hit() -> None:
    assert py(LOOP.format("interval")) == ["unwatched-loop:4"]


def test_rb3_a_loop_that_spawns_each_pass_is_a_hit_even_when_slow() -> None:
    src = "import subprocess, time\nwhile True:\n    subprocess.run(['git', 'status'])\n    time.sleep(60)\n"
    assert py(src) == ["unwatched-loop:2"]


def test_rb3_an_event_wait_paces_a_loop_and_a_re_arming_timer_is_a_loop() -> None:
    assert py("def run(stop):\n    while not stop.wait(1):\n        work()\n") == ["unwatched-loop:2"]
    assert py("import threading\ndef tick():\n    work()\n    threading.Timer(2, tick).start()\n") == ["unwatched-loop:4"]


def test_rb3_clean_slow_loops_one_shot_timers_and_declared_loops() -> None:
    assert py(LOOP.format("30")) == []
    assert py("PERIOD = 10\n" + LOOP.format("PERIOD")) == []
    assert py("import threading\ndef later():\n    threading.Timer(1, restart).start()\n") == []
    assert py(LOOP.format("1"), declared={"run": 1.0}) == []


# ------------------------------------------------- RB4 scan-per-request

WALK = "import os\n\ndef list_logs():\n    return list(os.walk('logs'))\n"


def test_rb4_a_walk_in_a_handler_module_is_a_hit() -> None:
    assert py(WALK, handler=True) == ["scan-per-request:4"]
    assert py("from pathlib import Path\ndef f(p: Path):\n    return list(p.rglob('*.log'))\n",
              handler=True) == ["scan-per-request:3"]


def test_rb4_clean_outside_a_handler_or_through_the_stat_cache() -> None:
    assert py(WALK) == []
    assert py("from src import stat_cache\n" + WALK, handler=True, stat_cache=("src.stat_cache",)) == []


# ----------------------------------------------------- RB5 default-pool

def test_rb5_the_shared_default_pool_is_a_hit() -> None:
    assert py("import asyncio\nasync def f():\n    await asyncio.to_thread(work)\n") == ["default-pool:3"]
    assert py("async def f(loop):\n    await loop.run_in_executor(None, work)\n") == ["default-pool:2"]


def test_rb5_clean_a_named_pool() -> None:
    assert py("async def f(loop, POOL):\n    await loop.run_in_executor(POOL, work)\n") == []


# ------------------------------------------------------- exempt markers

def test_a_marker_with_no_reason_exempts_nothing_and_is_itself_a_hit() -> None:
    src = "# request-budget-exempt\nimport asyncio\nasync def f():\n    await asyncio.to_thread(w)  # request-budget-exempt:\n"
    assert sorted(py(src)) == ["bare-exempt:1", "bare-exempt:4", "default-pool:4"]


def test_a_marker_reaches_the_hit_through_a_comment_block_only() -> None:
    above = "# request-budget-exempt: the boot read\n# it runs once\nimport asyncio\nasyncio.to_thread(w)\n"
    assert py(above) == ["default-pool:4"], "a code line breaks the block"
    block = "import asyncio\n# request-budget-exempt: the boot read\n# it runs once\nasyncio.to_thread(w)\n"
    assert py(block) == []


# ----------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert rb.parse_config('layer = "x"\n') is None
    assert rb.parse_config("[request_budget_ratchet]\nenabled = false\n") is None


def test_enabled_table_defaults_to_every_rule() -> None:
    cfg = rb.parse_config("[request_budget_ratchet]\nenabled = true\n")
    assert cfg is not None and cfg.rules == rb.RULES and cfg.handler_dirs == ()


@pytest.mark.parametrize("body", [
    pytest.param("enabled = true\nrule = []\n", id="typo-in-key"),
    pytest.param("enabled = true\nrules = ['poll-everything']\n", id="unknown-rule"),
    pytest.param("enabled = true\npoll_wrappers = ['not a name']\n", id="bad-wrapper"),
    pytest.param("enabled = true\n[request_budget]\nloops = [{path = 'a.py', function = 'f', interval_s = 1}]\n",
                 id="loop-without-why"),
    pytest.param("enabled = true\n[request_budget]\nloops = [{path = 'a.py', function = 'f', interval_s = 0, why = 'w'}]\n",
                 id="loop-zero-interval"),
    pytest.param("enabled = true\n[request_budget]\nvisible = 3\n", id="typo-in-budget"),
])
def test_a_malformed_table_is_a_config_error(body: str) -> None:
    with pytest.raises(rb.ConfigError):
        rb.parse_config("[request_budget_ratchet]\n" + body)


# ------------------------------------------------------------- ratchet

def run_mode(repo: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return rb.run(repo, init=init, update=update, allow_additions=allow)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    write(tmp_path, ".fleet.toml", "[request_budget_ratchet]\nenabled = true\nhandler_dirs = ['app/webapp/routers']\n")
    write(tmp_path, "app/webapp/static/main.js", "startPoll(read, 5000);\n")
    return tmp_path


def test_init_then_a_new_hit_rises_and_exits_one(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo, init=True) == rb.EXIT_PASS
    assert run_mode(repo) == rb.EXIT_PASS
    write(repo, "app/webapp/static/main.js", "startPoll(read, 5000);\nsetInterval(() => fetch('/x'), 9000);\n")
    assert run_mode(repo) == rb.EXIT_RISE
    assert "main.js:2: [fixed-rate-poll]" in capsys.readouterr().out


def test_existing_debt_passes_and_a_fix_hints_the_shrink(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "src/loop.py", "import time\nwhile True:\n    time.sleep(1)\n")
    assert run_mode(repo, init=True) == rb.EXIT_PASS
    assert run_mode(repo) == rb.EXIT_PASS
    write(repo, "src/loop.py", "import time\nwhile True:\n    time.sleep(30)\n")
    capsys.readouterr()
    assert run_mode(repo) == rb.EXIT_PASS
    assert "1 baselined hit(s) are gone" in capsys.readouterr().out
    assert run_mode(repo, update=True) == rb.EXIT_PASS
    assert '"entries": []' in (repo / rb.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_update_refuses_additions_unless_allowed(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/pool.py", "import asyncio\nasyncio.to_thread(f)\n")
    assert run_mode(repo, update=True) == rb.EXIT_RISE
    assert run_mode(repo, update=True, allow=True) == rb.EXIT_PASS
    assert run_mode(repo) == rb.EXIT_PASS


def test_init_never_overwrites_and_a_missing_baseline_fails(repo: Path) -> None:
    assert run_mode(repo) == rb.EXIT_RISE
    run_mode(repo, init=True)
    assert run_mode(repo, init=True) == rb.EXIT_CONFIG


def test_a_web_app_without_the_timing_middleware_is_one_hit_on_its_factory(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_mode(repo, init=True)
    write(repo, "app/webapp/server.py", "from fastapi import FastAPI\n\napp = FastAPI()\n")
    assert run_mode(repo) == rb.EXIT_RISE
    assert "server.py:3: [timing-middleware]" in capsys.readouterr().out
    write(repo, "app/webapp/server.py", "from fastapi import FastAPI\nfrom src.request_timing import "
                                        "RequestTimingMiddleware\n\napp = FastAPI()\n"
                                        "app.add_middleware(RequestTimingMiddleware)\n")
    assert run_mode(repo) == rb.EXIT_PASS


def test_the_middleware_import_may_live_outside_server_paths(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "app/webapp/server.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    write(repo, "webapp/wiring.py", "from src import request_timing\nrequest_timing.RequestTimingMiddleware\n")
    assert run_mode(repo) == rb.EXIT_PASS


def test_a_vendored_copy_is_never_scanned(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, ".fleet.toml", "[request_budget_ratchet]\nenabled = true\n"
                               "[vendored]\nbw = { src = 'x', dest = 'app/webapp/static/_vendored/bw' }\n")
    write(repo, "app/webapp/static/_vendored/bw/bw.js", "setInterval(() => fetch('/x'), 100);\n")
    assert run_mode(repo) == rb.EXIT_PASS


def test_exemptions_and_stale_declarations_are_printed(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, ".fleet.toml", "[request_budget_ratchet]\nenabled = true\n[request_budget]\n"
                               "loops = [{path = 'src/gone.py', function = 'run', interval_s = 1, why = 'w'}]\n")
    write(repo, "src/pool.py", "import asyncio\n# request-budget-exempt: a one-off boot read\nasyncio.to_thread(f)\n")
    run_mode(repo, init=True)
    capsys.readouterr()
    assert run_mode(repo) == rb.EXIT_PASS
    out = capsys.readouterr().out
    assert "1 exemption(s):" in out and "src/pool.py:3: [default-pool] a one-off boot read" in out
    assert "src/gone.py: run matches no loop any more" in out
    assert "scan-per-request: OFF" in out


@pytest.mark.parametrize(("rel", "body", "says"), [
    ("app/webapp/static/bad.js", b"const s = 'never closes;\n", "string does not close"),
    ("app/webapp/static/nested.js", b"const s = `a ${ b ? `: ${c}` : '' y;\nfoo();\n", "substitution does not close"),
    ("src/bad.py", b"def f(:\n", "does not parse"),
    ("src/latin.py", b"x = '\xe9'\n", "is not UTF-8"),
])
def test_a_file_it_cannot_read_through_is_not_confirmed(
    repo: Path, rel: str, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_unreadable_file_not_confirmed(rb, run_mode, repo, rel, body, says, capsys)


test_git_that_cannot_list_the_tree_is_not_confirmed = git_failure_test(rb, run_mode)


def test_the_script_runs_standalone_with_its_sibling(repo: Path) -> None:
    proc = subprocess.run([sys.executable, "-P", str(REPO_ROOT / "scripts" / "request_budget_ratchet.py"), "--root",
                           str(repo), "--init"], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------- self-adoption

def test_the_scaffold_enables_the_stage_with_a_baseline() -> None:
    cfg, _ = rb.load_config(REPO_ROOT)
    assert cfg is not None and (REPO_ROOT / cfg.baseline).is_file()


def test_gate_runs_the_stage_after_the_ux_surface_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (text.index(s) for s in (
        'Invoke-Stage "ux surface ratchet"', 'Invoke-Stage "request budget ratchet"', 'Invoke-Stage "mypy'))
    assert before < stage < mypy


def test_the_script_is_catalogued_with_its_sibling() -> None:
    from scripts.vendored_catalog import load_catalog

    catalog = load_catalog(REPO_ROOT)
    assert catalog["request_budget_ratchet"]["src"] == "scripts/request_budget_ratchet.py"
    assert catalog["request_budget_scan"]["src"] == "scripts/request_budget_scan.py"
    assert 'requires = ["request_budget_scan", "ratchet_baseline"]' in (REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8")


def test_every_rule_is_documented() -> None:
    doc = (REPO_ROOT / "docs" / "request-budget-ratchet.md").read_text(encoding="utf-8")
    for rule in rb.RULES:
        assert f"`{rule}`" in doc and f"`{rule}`" in (rb.__doc__ or ""), rule
