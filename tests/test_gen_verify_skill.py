"""Tests for the verify-skill generator (project-scaffolding#412).

Hermetic: a synthetic adopter under `tests/_fixtures/verify_skill/repo/` is read
statically, nothing of it is imported or booted. Four layers:

1. **Seeding** -- what the static parse finds in the fixture, and what it refuses
   to guess.
2. **Generation** -- the golden feature files, idempotence, and that hand-written
   text survives a regeneration.
3. **`--check`** -- `clean` / `changed` / `blocked`, one case per documented cause.
4. **The live half** -- an unreachable port is `blocked` (a real closed port, not a
   mock), and a real pytest junit XML is read the way a maintain run reads it.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from scripts import gen_verify_skill as gen
from src.no_window import NO_WINDOW

FIXTURES = Path(__file__).resolve().parent / "_fixtures" / "verify_skill"
FIXTURE_REPO = FIXTURES / "repo"
EXPECTED = FIXTURES / "expected"
APP = "jobs-app"

NODES = [
    "tests/e2e/test_jobs.py::TestFilters::test_open_sheet",
    "tests/e2e/test_jobs.py::test_jobs_empty_or_error",
    "tests/e2e/test_jobs.py::test_jobs_list",
    "tests/e2e/test_smoke.py::test_settings_pane",
]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway copy of the fixture adopter the test is free to edit."""
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE_REPO, dest)
    return dest


@pytest.fixture
def skill(repo: Path, tmp_path: Path) -> Path:
    """The fixture adopter's skill, generated once into `tmp_path/skill`."""
    out = tmp_path / "skill"
    assert gen.main(["--repo", str(repo), "--app", APP, "--out", str(out)]) == 0
    return out


def check(repo: Path, out: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, str]:
    rc = gen.main(["--repo", str(repo), "--app", APP, "--out", str(out), "--check", *extra])
    return rc, capsys.readouterr().out


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ------------------------------------------------------------------ seeding


def test_surface_sites_are_read_statically_with_their_pytest_node() -> None:
    sites, unresolved = gen.collect_surface_sites(FIXTURE_REPO)
    assert ("jobs.list", "tests/e2e/test_jobs.py::test_jobs_list") in sites
    assert ("jobs.list", "tests/e2e/test_smoke.py::test_settings_pane") in sites  # the same name in two tests
    assert ("filters.sheet", "tests/e2e/test_jobs.py::TestFilters::test_open_sheet") in sites  # a class method
    # `surface(page, "a" if broken else "b")`: both branches are literal, so both are mapped
    assert ("jobs.error", "tests/e2e/test_jobs.py::test_jobs_empty_or_error") in sites
    assert ("jobs.empty", "tests/e2e/test_jobs.py::test_jobs_empty_or_error") in sites


def test_a_call_the_parse_cannot_map_is_listed_never_dropped() -> None:
    sites, unresolved = gen.collect_surface_sites(FIXTURE_REPO)
    assert not any(name == "jobs.hidden" for name, _ in sites)  # a helper is not a pytest node
    assert any("test_dynamic_name" in u and "not a string literal" in u for u in unresolved)
    assert any("_open_hidden" in u and "outside a test function" in u for u in unresolved)


def test_views_group_by_prefix_and_record_every_seed_in_order() -> None:
    model = gen.build_model(FIXTURE_REPO, APP)
    seeds = {v.slug: v.seeds for v in model.views}
    assert seeds == {
        "about": {"key views"},  # a key view no surface() name covers still gets a file
        "filters": {"surface()", "extra_steps"},
        "home": {"key views"},  # `/` is the home route
        "jobs": {"surface()"},
        "settings": {"surface()", "key views"},
    }
    assert model.nodes == NODES


def test_key_views_come_only_from_the_ux_surface_block() -> None:
    text = (FIXTURE_REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert [r for r, _ in gen.parse_key_views(text)] == ["/", "/settings", "/about"]  # not /not-this-one
    assert gen.parse_key_views("# no such block\n") == []


def test_declared_e2e_surfaces_are_context_not_seeds() -> None:
    model = gen.build_model(FIXTURE_REPO, APP)
    assert model.e2e_surfaces == [("jobs", ["tests/e2e/test_jobs.py"])]
    assert "jobs" in {v.slug for v in model.views}  # present because of surface(), not because of [[e2e.surface]]


def test_a_file_that_cannot_be_parsed_is_an_error_not_a_skip(repo: Path) -> None:
    (repo / "tests/e2e/test_broken.py").write_text("def test_x(:\n", encoding="utf-8")
    with pytest.raises(gen.GeneratorError, match="test_broken.py"):
        gen.build_model(repo, APP)


def test_a_repo_without_fleet_toml_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(gen.GeneratorError, match=r"\.fleet\.toml"):
        gen.build_model(tmp_path, APP)


# --------------------------------------------------------------- generation


def test_generated_feature_files_match_the_golden_files(skill: Path) -> None:
    for name in ("README.md", "filters.md"):
        assert (skill / "features" / name).read_text(encoding="utf-8") == (EXPECTED / "features" / name).read_text(encoding="utf-8")


def test_skill_md_carries_every_section_filled_from_verify(skill: Path) -> None:
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    for heading in ("## Launch", "## Doctor", "## Drive", "## Evidence", "## Cleanup", "## Maintain", "## Gotchas"):
        assert heading in text
    assert "name: verify-jobs-app" in text
    assert "`JOBS_DATA_DIR`" in text and "`JOBS_E2E_LIVE`" in text and "tests/e2e/conftest.py::boot_instance" in text
    assert "(`:8123`" in text  # the live port from .fleet.toml, named as the one never to share
    assert f"{gen.FILL} set" not in text and "{{" not in text  # no placeholder, no unfilled template field
    assert "taskkill /IM" in text  # Cleanup names what never to do


def test_two_runs_are_byte_identical(repo: Path, skill: Path, tmp_path: Path) -> None:
    before = tree(skill)
    assert gen.main(["--repo", str(repo), "--app", APP, "--out", str(skill)]) == 0
    assert tree(skill) == before
    other = tmp_path / "other"
    assert gen.main(["--repo", str(repo), "--app", APP, "--out", str(other)]) == 0
    assert tree(other) == before  # a fresh tree equals a regenerated one


def test_hand_written_text_survives_a_regeneration(repo: Path, skill: Path) -> None:
    jobs = skill / "features" / "jobs.md"
    jobs.write_text(jobs.read_text(encoding="utf-8").replace("_None recorded yet._", "- The list paints late on a cold start."), encoding="utf-8")
    skill_md = skill / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\n## Notes\n\nMine.\n", encoding="utf-8")
    (repo / "tests/e2e/test_jobs.py").write_text(
        (repo / "tests/e2e/test_jobs.py").read_text(encoding="utf-8") + '\n\ndef test_extra(page):\n    surface(page, "jobs.extra")\n',
        encoding="utf-8",
    )
    assert gen.main(["--repo", str(repo), "--app", APP, "--out", str(skill)]) == 0
    regenerated = jobs.read_text(encoding="utf-8")
    assert "- The list paints late on a cold start." in regenerated  # the Gotchas section
    assert "`jobs.extra`" in regenerated  # the generated block moved on
    assert "## Notes\n\nMine." in skill_md.read_text(encoding="utf-8")


def test_a_hand_edit_inside_a_generated_block_is_replaced(repo: Path, skill: Path) -> None:
    skill_md = skill / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8").replace("## Cleanup", "## Cleanup (edited)"), encoding="utf-8")
    gen.main(["--repo", str(repo), "--app", APP, "--out", str(skill)])
    assert "## Cleanup (edited)" not in skill_md.read_text(encoding="utf-8")


def test_a_block_the_template_added_later_goes_before_gotchas(repo: Path, skill: Path) -> None:
    skill_md = skill / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    start, end = text.index("<!-- gen:begin maintain -->"), text.index("<!-- gen:end maintain -->") + len("<!-- gen:end maintain -->\n")
    skill_md.write_text(text[:start] + text[end:].lstrip("\n"), encoding="utf-8")  # an older skill without Maintain
    gen.main(["--repo", str(repo), "--app", APP, "--out", str(skill)])
    regrown = skill_md.read_text(encoding="utf-8")
    assert regrown.index("\n## Maintain") < regrown.index("\n## Gotchas")


def test_unpaired_markers_fail_loud(repo: Path, skill: Path) -> None:
    (skill / "features" / "jobs.md").write_text("<!-- gen:begin feature -->\nno end marker\n", encoding="utf-8")
    assert gen.main(["--repo", str(repo), "--app", APP, "--out", str(skill)]) == 2


def test_generation_never_touches_the_adopter_repo(repo: Path, tmp_path: Path) -> None:
    before = tree(repo)
    assert gen.main(["--repo", str(repo), "--app", APP, "--out", str(tmp_path / "out")]) == 0
    assert gen.main(["--repo", str(repo), "--app", APP, "--out", str(tmp_path / "out"), "--check"]) == 0
    assert tree(repo) == before


def test_default_location_prints_the_gitignore_allowlist_and_edits_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert gen.main(["--repo", str(repo), "--app", APP]) == 0
    assert "!/.claude/skills/verify-jobs-app/" in capsys.readouterr().out
    assert (repo / ".claude" / "skills" / "verify-jobs-app" / "SKILL.md").is_file()
    assert not (repo / ".gitignore").exists()


def test_a_missing_verify_table_is_a_visible_placeholder_never_a_guess(repo: Path, tmp_path: Path) -> None:
    toml = (repo / ".fleet.toml").read_text(encoding="utf-8")
    (repo / ".fleet.toml").write_text(toml[: toml.index("[verify]")] + toml[toml.index("[[design"):], encoding="utf-8")
    out = tmp_path / "out"
    assert gen.main(["--repo", str(repo), "--app", APP, "--out", str(out)]) == 0
    text = (out / "SKILL.md").read_text(encoding="utf-8")
    assert f"{gen.FILL} set `boot`" in text and f"{gen.FILL} set `live_optin_env`" in text
    assert "`JOBS_APP_DATA_DIR`" in text  # the documented default for data_dir_env, via app_dir_env_var


# -------------------------------------------------------------------- check


def test_an_in_sync_skill_is_static_clean(repo: Path, skill: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = check(repo, skill, capsys)
    assert rc == 0
    assert out.splitlines()[-1] == "STATIC=clean"


def test_a_new_surface_name_is_changed_and_named(repo: Path, skill: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = repo / "tests/e2e/test_jobs.py"
    path.write_text(path.read_text(encoding="utf-8") + '\n\ndef test_extra(page):\n    surface(page, "jobs.extra")\n', encoding="utf-8")
    rc, out = check(repo, skill, capsys)
    assert rc == 1
    assert "new sub-feature not in the map" in out and "extra `jobs.extra`" in out
    assert out.splitlines()[-1] == "STATIC=changed"


def test_a_removed_test_is_changed_and_named(repo: Path, skill: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = repo / "tests/e2e/test_jobs.py"
    path.write_text(path.read_text(encoding="utf-8").replace('surface(page, "filters.sheet")', "pass"), encoding="utf-8")
    rc, out = check(repo, skill, capsys)
    assert rc == 1
    assert "mapped sub-feature no longer seeded" in out and "filters.sheet" in out
    assert (skill / "features" / "filters.md").is_file()  # the view keeps its extra_steps seed; nothing is deleted


def test_a_view_that_lost_every_seed_is_changed_and_left_in_place(repo: Path, skill: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (skill / "features" / "retired.md").write_text("# retired\n\n## Gotchas\n\n- a hand-written trap\n", encoding="utf-8")
    rc, out = check(repo, skill, capsys)
    assert rc == 1
    assert "features/retired.md: no longer has a seed" in out
    gen.main(["--repo", str(repo), "--app", APP, "--out", str(skill)])
    assert "a hand-written trap" in (skill / "features" / "retired.md").read_text(encoding="utf-8")  # never deleted


def test_a_moved_driving_node_is_changed(repo: Path, skill: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = repo / "tests/e2e/test_jobs.py"
    path.write_text(path.read_text(encoding="utf-8").replace("def test_jobs_list(", "def test_jobs_listing("), encoding="utf-8")
    rc, out = check(repo, skill, capsys)
    assert rc == 1
    assert "driving node changed for" in out


def test_a_changed_selector_is_changed(repo: Path, skill: Path, capsys: pytest.CaptureFixture[str]) -> None:
    toml = repo / ".fleet.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("[data-open-filters]", "[data-open-filter-sheet]"), encoding="utf-8")
    rc, out = check(repo, skill, capsys)
    assert rc == 1
    assert "features/filters.md" in out


def test_a_missing_verify_table_is_blocked(repo: Path, skill: Path, capsys: pytest.CaptureFixture[str]) -> None:
    toml = (repo / ".fleet.toml").read_text(encoding="utf-8")
    (repo / ".fleet.toml").write_text(toml[: toml.index("[verify]")] + toml[toml.index("[[design"):], encoding="utf-8")
    rc, out = check(repo, skill, capsys)
    assert rc == 2
    assert "[verify] incomplete" in out and out.splitlines()[-1] == "STATIC=blocked"


def test_no_generated_skill_is_blocked_not_clean(repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = check(repo, tmp_path / "nothing-here", capsys)
    assert rc == 2
    assert "no generated skill" in out and out.splitlines()[-1] == "STATIC=blocked"


# ---------------------------------------------------------------- live half


def junit(tmp_path: Path, outcomes: dict[str, str]) -> Path:
    """A junit XML written by hand: node -> passed | failure | error | skipped | (absent)."""
    cases = []
    for node, outcome in outcomes.items():
        path, *rest = node.split("::")
        classname = ".".join([path.removesuffix(".py").replace("/", "."), *rest[:-1]])
        child = "" if outcome == "passed" else f"<{outcome}/>"
        cases.append(f'<testcase classname="{classname}" name="{rest[-1]}">{child}</testcase>')
    xml = tmp_path / "maintain.xml"
    xml.write_text(f'<testsuites><testsuite name="pytest">{"".join(cases)}</testsuite></testsuites>', encoding="utf-8")
    return xml


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
        self.send_response(200 if self.path == "/healthz" else 500)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def instance() -> str:
    """A real HTTP server on a free loopback port, answering /healthz with 200."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"  # the socket is closed: nothing listens here


def all_passed(tmp_path: Path) -> Path:
    return junit(tmp_path, dict.fromkeys(NODES, "passed"))


def test_an_answering_instance_and_all_nodes_passing_is_clean(repo: Path, skill: Path, tmp_path: Path, instance: str, capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = check(repo, skill, capsys, "--live-url", instance, "--junit", str(all_passed(tmp_path)))
    assert rc == 0
    assert out.splitlines()[-1] == "MAINTAIN=clean"


def test_an_unreachable_app_is_blocked_even_when_everything_else_is_green(repo: Path, skill: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = check(repo, skill, capsys, "--live-url", closed_port_url(), "--junit", str(all_passed(tmp_path)))
    assert rc == 2
    assert "STATIC=clean" in out and "unreachable" in out
    assert out.splitlines()[-1] == "MAINTAIN=blocked"


def test_a_ready_path_that_does_not_answer_200_is_blocked(repo: Path, skill: Path, tmp_path: Path, instance: str, capsys: pytest.CaptureFixture[str]) -> None:
    toml = repo / ".fleet.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('"/healthz"', '"/nope"'), encoding="utf-8")
    gen.main(["--repo", str(repo), "--app", APP, "--out", str(skill)])  # keep the skill in sync with the edit
    rc, out = check(repo, skill, capsys, "--live-url", instance, "--junit", str(all_passed(tmp_path)))
    assert rc == 2
    assert "HTTP 500" in out and out.splitlines()[-1] == "MAINTAIN=blocked"


@pytest.mark.parametrize("outcome", ["failure", "error", "skipped"])
def test_a_mapped_node_that_did_not_pass_is_blocked(repo: Path, skill: Path, tmp_path: Path, instance: str, capsys: pytest.CaptureFixture[str], outcome: str) -> None:
    results = dict.fromkeys(NODES, "passed")
    results[NODES[2]] = outcome
    rc, out = check(repo, skill, capsys, "--live-url", instance, "--junit", str(junit(tmp_path, results)))
    assert rc == 2
    assert f"{NODES[2]}: {outcome}" in out and out.splitlines()[-1] == "MAINTAIN=blocked"


def test_a_mapped_node_missing_from_the_junit_is_blocked_not_assumed_green(repo: Path, skill: Path, tmp_path: Path, instance: str, capsys: pytest.CaptureFixture[str]) -> None:
    results = dict.fromkeys(NODES[:3], "passed")
    rc, out = check(repo, skill, capsys, "--live-url", instance, "--junit", str(junit(tmp_path, results)))
    assert rc == 2
    assert f"{NODES[3]}: not in the junit XML" in out


def test_an_unreadable_junit_is_blocked(repo: Path, skill: Path, tmp_path: Path, instance: str, capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = check(repo, skill, capsys, "--live-url", instance, "--junit", str(tmp_path / "missing.xml"))
    assert rc == 2 and "unreadable" in out


def test_a_stale_map_with_a_healthy_app_is_changed_not_clean(repo: Path, skill: Path, tmp_path: Path, instance: str, capsys: pytest.CaptureFixture[str]) -> None:
    path = repo / "tests/e2e/test_jobs.py"
    path.write_text(path.read_text(encoding="utf-8") + '\n\ndef test_extra(page):\n    surface(page, "jobs.extra")\n', encoding="utf-8")
    results = dict.fromkeys([*NODES, "tests/e2e/test_jobs.py::test_extra"], "passed")
    rc, out = check(repo, skill, capsys, "--live-url", instance, "--junit", str(junit(tmp_path, results)))
    assert rc == 1
    assert out.splitlines()[-1] == "MAINTAIN=changed"


def test_live_evidence_needs_both_flags_or_neither(repo: Path, skill: Path, tmp_path: Path, instance: str) -> None:
    base = ["--repo", str(repo), "--app", APP, "--out", str(skill), "--check"]
    with pytest.raises(SystemExit) as one:
        gen.main([*base, "--live-url", instance])
    assert one.value.code == 2  # a MAINTAIN verdict without the junit would be a guess
    with pytest.raises(SystemExit) as other:
        gen.main([*base, "--junit", str(all_passed(tmp_path))])
    assert other.value.code == 2
    with pytest.raises(SystemExit) as stray:
        gen.main(["--repo", str(repo), "--live-url", instance, "--junit", str(all_passed(tmp_path))])
    assert stray.value.code == 2  # evidence flags without --check


def test_junit_from_a_real_pytest_run_maps_every_node(tmp_path: Path) -> None:
    """The classname/name shape is pytest's, not ours: run pytest and read what it wrote."""
    project = tmp_path / "project"
    (project / "tests" / "e2e").mkdir(parents=True)
    (project / "tests" / "e2e" / "test_jobs.py").write_text(
        textwrap.dedent(
            """
            import pytest

            def test_jobs_list():
                pass

            @pytest.mark.parametrize("variant", [1, 2])
            def test_jobs_empty_or_error(variant):
                assert variant < 2

            class TestFilters:
                def test_open_sheet(self):
                    pass
            """
        ),
        encoding="utf-8",
    )
    (project / "tests" / "e2e" / "test_smoke.py").write_text("def test_settings_pane():\n    pass\n", encoding="utf-8")
    xml = project / "out.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}", "tests/e2e"],
        cwd=project, capture_output=True, text=True, check=False, creationflags=NO_WINDOW,
    )
    # one parametrized variant failed, so that node is a problem; every other node resolved and passed
    assert gen.junit_problems(xml, NODES) == [f"{NODES[1]}: failure"]
    assert gen.junit_problems(xml, [*NODES, "tests/e2e/test_jobs.py::test_gone"]) == [
        f"{NODES[1]}: failure",
        "tests/e2e/test_jobs.py::test_gone: not in the junit XML (never ran)",
    ]
