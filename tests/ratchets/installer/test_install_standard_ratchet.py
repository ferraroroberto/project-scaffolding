"""The install standard ratchet: installer vendored at the scaffold's content, a migration table, a playbook.

Each rule runs on a throwaway repo built from this scaffold's own installer modules, so a hit is the
real one an adopter would see; the hashes the script carries are held to this scaffold's modules.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import install_standard_ratchet as isr
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "install_standard_ratchet.py"
TEMPLATE_BAT = REPO_ROOT / "scripts" / "templates" / "setup.bat"
TEMPLATE_PLAYBOOK = REPO_ROOT / "docs" / "templates" / "install-playbook.md"

PLAYBOOK = "# Install, update and migrate\n\n## Install\n\ntext\n\n## Update\n\ntext\n\n## Migrate\n\ntext\n"
FLEET = """\
port = 8130

[install_standard_ratchet]
enabled = true

[install.endpoint]
version_path = "/api/version"

[install.migrate]
copy    = ["config/config.json"]
secrets = [".env"]

[vendored]
installer         = { src = "src/installer.py" }
installer_migrate = { src = "src/installer_migrate.py" }
installer_declaration = { src = "src/installer_declaration.py" }
installer_inplace = { src = "src/installer_inplace.py" }
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo that meets the standard: the installer modules, the tables, the playbook, setup.bat."""
    (tmp_path / "src").mkdir()
    for rel, _ in isr.INSTALLER.values():
        shutil.copyfile(REPO_ROOT / rel, tmp_path / rel)
    shutil.copyfile(TEMPLATE_BAT, tmp_path / "setup.bat")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/install.md").write_text(PLAYBOOK, encoding="utf-8")
    (tmp_path / ".fleet.toml").write_text(FLEET, encoding="utf-8")
    return tmp_path


def hits(root: Path, playbook: str = "docs/install.md", setup: str = "setup.bat") -> dict[str, str]:
    return isr.scan(root, isr.read_toml(root), playbook, setup)


def run(root: Path, *args: str) -> int:
    return isr.run(root, init="--init" in args, update="--update-baseline" in args,
                   allow_additions="--allow-additions" in args)


def test_the_carried_hashes_are_this_scaffolds_installer() -> None:
    stale = {key: rel for key, (rel, digest) in isr.INSTALLER.items() if isr.content_hash(REPO_ROOT / rel) != digest}
    assert not stale, (f"update INSTALLER in scripts/install_standard_ratchet.py to the new content of {stale}: "
                       "the ratchet pins the installer adopters must carry")


def test_the_keys_are_the_scaffolds_components() -> None:
    components = isr.read_toml(REPO_ROOT)["components"]
    for key, (rel, _) in isr.INSTALLER.items():
        assert components[key]["src"] == rel


def test_a_repo_that_meets_the_standard_has_no_hit(repo: Path) -> None:
    assert hits(repo) == {}


def test_a_crlf_copy_still_matches(repo: Path) -> None:
    path = repo / "src/installer.py"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert hits(repo) == {}


def test_a_missing_undeclared_and_stale_module_are_each_a_hit(repo: Path) -> None:
    (repo / "src/installer_inplace.py").unlink()
    (repo / ".fleet.toml").write_text(FLEET.replace('installer_migrate = { src = "src/installer_migrate.py" }\n', ""),
                                      encoding="utf-8")
    with (repo / "src/installer.py").open("a", encoding="utf-8") as fh:
        fh.write("# a local edit\n")
    found = hits(repo)
    assert "missing" in found["installer-vendored: src/installer_inplace.py"]
    assert "not declared" in found["installer-vendored: src/installer_migrate.py"]
    assert "differs" in found["installer-vendored: src/installer.py"]


def test_a_missing_declaration_module_is_a_hit_on_both_rules(repo: Path) -> None:
    (repo / "src/installer_declaration.py").unlink()
    found = hits(repo)
    assert "missing" in found["installer-vendored: src/installer_declaration.py"]
    assert found["migrate-table"] == "src/installer_declaration.py is missing, so [install.migrate] cannot be parsed"


def test_a_missing_migration_table_is_a_hit(repo: Path) -> None:
    text = FLEET.split("[install.migrate]")[0] + "[vendored]" + FLEET.split("[vendored]")[1]
    (repo / ".fleet.toml").write_text(text, encoding="utf-8")
    assert hits(repo) == {"migrate-table": "[install.migrate] is not declared"}


def test_a_malformed_migration_table_names_the_key(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(FLEET.replace('copy    = ["config/config.json"]', 'copy = ["C:/abs"]'),
                                      encoding="utf-8")
    assert "copy entry 'C:/abs' must be a path inside the repo" in hits(repo)["migrate-table"]


def test_a_malformed_endpoint_is_a_migration_hit(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(FLEET.replace('version_path = "/api/version"', 'version_path = "api"'),
                                      encoding="utf-8")
    assert "version_path" in hits(repo)["migrate-table"]


def test_no_migrate_module_means_the_table_cannot_be_parsed(repo: Path) -> None:
    (repo / "src/installer_migrate.py").unlink()
    assert "cannot be parsed" in hits(repo)["migrate-table"]


def test_a_migrate_module_that_does_not_load_is_not_confirmed(repo: Path) -> None:
    (repo / "src/installer_migrate.py").write_text("raise RuntimeError('broken')\n", encoding="utf-8")
    (repo / ".ratchets").mkdir()
    (repo / ".ratchets/install-standard.json").write_text(isr.render_baseline([]), encoding="utf-8")
    with pytest.raises(isr.NotConfirmed, match="does not load"):
        hits(repo)
    assert run(repo) == isr.EXIT_NOT_CONFIRMED


def test_a_missing_playbook_and_section_are_hits(repo: Path) -> None:
    (repo / "docs/install.md").write_text(PLAYBOOK.replace("## Migrate", "## Migrate from an existing install"),
                                          encoding="utf-8")
    assert hits(repo) == {"playbook-sections: docs/install.md ## Migrate": "no `## Migrate` section"}
    (repo / "docs/install.md").unlink()
    assert list(hits(repo)) == ["playbook-sections: docs/install.md"]


def test_a_heading_inside_a_fence_does_not_count(repo: Path) -> None:
    fenced = PLAYBOOK.replace("## Update\n", "```markdown\n## Update\n```\n")
    (repo / "docs/install.md").write_text(fenced, encoding="utf-8")
    assert list(hits(repo)) == ["playbook-sections: docs/install.md ## Update"]


def drop_lines(path: Path, needle: str) -> None:
    """Remove every non-comment line of a batch file that holds `needle`."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [line for line in lines if line.lstrip().upper().startswith("REM") or needle not in line]
    assert kept != lines, f"{needle!r} is on no code line of {path.name}"
    path.write_text("".join(kept), encoding="utf-8")


def test_a_setup_bat_without_replace_fails_naming_the_file_and_flag(
        repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / ".ratchets").mkdir()
    (repo / ".ratchets/install-standard.json").write_text(isr.render_baseline([]), encoding="utf-8")
    assert run(repo) == isr.EXIT_PASS, capsys.readouterr().out
    # The comments and the error message still mention -Replace: neither offers it.
    drop_lines(repo / "setup.bat", '=="-Replace"')
    assert list(hits(repo)) == ["setup-flags: setup.bat -Replace"]
    capsys.readouterr()
    assert run(repo) == isr.EXIT_RISE
    assert "[setup-flags] setup.bat -Replace: does not offer -Replace" in capsys.readouterr().out


def test_each_entry_point_needs_the_line_that_runs_it(repo: Path) -> None:
    drop_lines(repo / "setup.bat", "installer_inplace.py")
    assert list(hits(repo)) == ["setup-flags: setup.bat -Replace", "setup-flags: setup.bat -InPlace"]
    shutil.copyfile(TEMPLATE_BAT, repo / "setup.bat")
    drop_lines(repo / "setup.bat", "installer.py")
    assert list(hits(repo)) == ["setup-flags: setup.bat -MigrateFrom"]
    (repo / "setup.bat").unlink()
    assert list(hits(repo)) == ["setup-flags: setup.bat"]


def test_the_entry_points_are_the_ones_the_playbook_template_names() -> None:
    migrate = TEMPLATE_PLAYBOOK.read_text(encoding="utf-8").split("## Migrate\n")[-1]
    named = set(re.findall(r"setup\.bat`? (?:already has `)?(-[A-Za-z]+)", migrate))
    assert named == set(isr.ENTRY_POINTS), (
        "update ENTRY_POINTS in scripts/install_standard_ratchet.py: the ratchet holds every adopter's "
        "setup.bat to the migrate entry points the playbook names")


def test_config_rejects_unknown_keys_and_outside_paths() -> None:
    with pytest.raises(isr.ConfigError, match="unknown key"):
        isr.parse_config({"install_standard_ratchet": {"enabled": True, "rules": []}})
    for key in ("playbook", "setup"):
        with pytest.raises(isr.ConfigError, match="inside the repo"):
            isr.parse_config({"install_standard_ratchet": {"enabled": True, key: "../x"}})
    assert isr.parse_config({"install_standard_ratchet": {"enabled": False}}) is None
    assert isr.parse_config({}) is None


def test_modes_init_check_shrink_and_additions(repo: Path) -> None:
    (repo / "docs/install.md").unlink()
    assert run(repo) == isr.EXIT_RISE, "a missing baseline fails"
    assert run(repo, "--init") == isr.EXIT_PASS
    assert isr.read_baseline(repo / ".ratchets/install-standard.json") == ["playbook-sections: docs/install.md"]
    assert run(repo, "--init") == isr.EXIT_CONFIG, "--init never overwrites"
    assert run(repo) == isr.EXIT_PASS
    (repo / "src/installer_inplace.py").unlink()
    assert run(repo) == isr.EXIT_RISE, "a new hit fails"
    assert run(repo, "--update-baseline") == isr.EXIT_RISE, "the update refuses an addition"
    assert run(repo, "--update-baseline", "--allow-additions") == isr.EXIT_PASS
    assert len(isr.read_baseline(repo / ".ratchets/install-standard.json")) == 2
    (repo / "docs/install.md").write_text(PLAYBOOK, encoding="utf-8")
    shutil.copyfile(REPO_ROOT / "src/installer_inplace.py", repo / "src/installer_inplace.py")
    assert run(repo, "--update-baseline") == isr.EXIT_PASS
    assert isr.read_baseline(repo / ".ratchets/install-standard.json") == []


def test_this_repo_holds_its_template_and_passes() -> None:
    assert hits(REPO_ROOT, "docs/templates/install-playbook.md", "scripts/templates/setup.bat") == {
        "migrate-table": "[install.migrate] is not declared"}
    proc = subprocess.run([sys.executable, "-P", str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", creationflags=NO_WINDOW, timeout=120, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASS" in proc.stdout
