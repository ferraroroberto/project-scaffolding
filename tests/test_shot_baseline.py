"""scripts/shot_baseline.py: config, the two raster bands, and every exit state on a throwaway repo."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from PIL import Image

from scripts import shot_baseline as sb
from tests._git_repo import git

_ENABLED = '[shot_baseline]\nenabled = true\nshots_dir = "shots"\n'


def _png(path: Path, *, changes: int = 0, delta: int = 0, size: tuple[int, int] = (100, 100)) -> None:
    """A flat grey image with the first *changes* pixels shifted by *delta* on the red channel."""
    image = Image.new("RGB", size, (128, 128, 128))
    pixels = image.load()
    assert pixels is not None
    for i in range(changes):
        pixels[i % size[0], i // size[0]] = (128 + delta, 128, 128)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _cfg(**overrides: object) -> sb.Config:
    cfg = sb.parse_config(_ENABLED)
    assert cfg is not None
    return sb.Config(**{**cfg.__dict__, **overrides})  # type: ignore[arg-type]


# ----------------------------------------------------------------- config

def test_absent_or_disabled_table_is_the_declared_skip() -> None:
    assert sb.parse_config("") is None
    assert sb.parse_config("[shot_baseline]\nenabled = false\n") is None


def test_defaults_are_the_measured_bands() -> None:
    cfg = sb.parse_config("[shot_baseline]\nenabled = true\n")
    assert cfg is not None
    assert (cfg.shots_dir, cfg.capture) == ("tests/e2e/shots", sb.DEFAULT_CAPTURE)
    assert (cfg.raster_max_delta, cfg.raster_max_pixels, cfg.glyph_max_delta, cfg.glyph_max_pixels) == (2, 500, 24, 64)


@pytest.mark.parametrize("body", [
    "typo = 1",
    "shots_dir = '../elsewhere'",
    "capture = []",
    "raster_max_delta = 300",
    "glyph_max_pixels = -1",
    "allowed_to_differ = { 'a.png' = '' }",
    "allowed_to_differ = { 'a.jpg' = 'why' }",
])
def test_malformed_config_fails_loud(body: str) -> None:
    with pytest.raises(sb.ConfigError):
        sb.parse_config(f"[shot_baseline]\nenabled = true\n{body}\n")


def test_non_boolean_enabled_fails_loud() -> None:
    with pytest.raises(sb.ConfigError):
        sb.parse_config("[shot_baseline]\nenabled = 'yes'\n")


# ------------------------------------------------------------- the bands

@pytest.mark.parametrize(("changes", "delta", "visible"), [
    (0, 0, False),        # identical pixels
    (500, 2, False),      # raster band: many pixels, a level or two
    (64, 24, False),      # glyph band: one icon stroke's edge
    (501, 2, True),       # just past the raster band's pixel count
    (65, 24, True),       # just past the glyph band's pixel count
    (35, 100, True),      # a real change: one digit of a timestamp
])
def test_visible_difference_bands(tmp_path: Path, changes: int, delta: int, visible: bool) -> None:
    _png(tmp_path / "a.png")
    _png(tmp_path / "b.png", changes=changes, delta=delta)
    assert (sb.visible_difference(tmp_path / "a.png", tmp_path / "b.png", _cfg()) is not None) is visible


def test_a_size_change_is_visible(tmp_path: Path) -> None:
    _png(tmp_path / "a.png")
    _png(tmp_path / "b.png", size=(100, 101))
    assert "size" in (sb.visible_difference(tmp_path / "a.png", tmp_path / "b.png", _cfg()) or "")


def test_an_unreadable_image_is_not_confirmed(tmp_path: Path) -> None:
    _png(tmp_path / "a.png")
    (tmp_path / "b.png").write_bytes(b"not a png")
    with pytest.raises(sb.NotConfirmed):
        sb.visible_difference(tmp_path / "a.png", tmp_path / "b.png", _cfg())


# ------------------------------------------------- check-tree on a git repo

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repo whose index holds two flat shots as the baseline."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(_ENABLED, encoding="utf-8")
    _png(tmp_path / "shots" / "home-phone-light.png")
    _png(tmp_path / "shots" / "home-phone-dark.png")
    git(tmp_path, "add", "-f", "shots")
    # Written well before any test's run starts, so only `_recapture` counts as recaptured.
    for shot in (tmp_path / "shots").glob("*.png"):
        os.utime(shot, (time.time() - 600, time.time() - 600))
    return tmp_path


def _recapture(path: Path, **kwargs: int) -> None:
    _png(path, **kwargs)
    now = time.time()
    os.utime(path, (now, now))


def test_byte_identical_recapture_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    since = time.time()
    _recapture(repo / "shots" / "home-phone-light.png")
    _recapture(repo / "shots" / "home-phone-dark.png")
    assert sb.run(repo, mode="check-tree", since=since) == sb.EXIT_PASS
    assert "2 of 2 committed shot(s) recaptured, 0 drifted" in capsys.readouterr().out


def test_raster_jitter_passes_and_is_reported_then_restored(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    since = time.time()
    _recapture(repo / "shots" / "home-phone-light.png", changes=300, delta=1)
    assert sb.run(repo, mode="check-tree", since=since) == sb.EXIT_PASS
    out = capsys.readouterr().out
    assert "raster:  home-phone-light.png" in out and "1 of 2 committed shot(s) recaptured" in out
    git(repo, "diff", "--quiet", "--", "shots")


def test_visible_change_fails_and_is_restored(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    since = time.time()
    _recapture(repo / "shots" / "home-phone-dark.png", changes=200, delta=100)
    assert sb.run(repo, mode="check-tree", since=since) == sb.EXIT_DRIFT
    assert "DRIFTED: home-phone-dark.png -- 200 px, worst channel delta 100" in capsys.readouterr().out
    git(repo, "diff", "--quiet", "--", "shots")


def test_a_failure_mid_comparison_still_restores_every_rewritten_shot(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    since = time.time()
    _recapture(repo / "shots" / "home-phone-light.png", changes=200, delta=100)
    _recapture(repo / "shots" / "home-phone-dark.png", changes=200, delta=100)
    judged: list[str] = []

    def judge_then_die(name: str, *args: object) -> None:
        judged.append(name)
        if len(judged) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(sb, "_judge", judge_then_die)
    with pytest.raises(KeyboardInterrupt):
        sb.run(repo, mode="check-tree", since=since)
    assert len(judged) == 2
    git(repo, "diff", "--quiet", "--", "shots")  # both recaptured PNGs are back to the committed copy


def test_allowlisted_shot_passes_with_its_reason(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / ".fleet.toml").write_text(
        _ENABLED + '[shot_baseline.allowed_to_differ]\n"home-phone-dark.png" = "shows uptime"\n', encoding="utf-8")
    since = time.time()
    _recapture(repo / "shots" / "home-phone-dark.png", changes=200, delta=100)
    assert sb.run(repo, mode="check-tree", since=since) == sb.EXIT_PASS
    assert "allowed: home-phone-dark.png -- shows uptime" in capsys.readouterr().out


def test_nothing_recaptured_is_not_confirmed_never_a_pass(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert sb.run(repo, mode="check-tree", since=time.time() + 60) == sb.EXIT_NOT_CONFIRMED
    assert "recaptured none of the 2" in capsys.readouterr().out


def test_unrecaptured_modification_is_left_alone(repo: Path) -> None:
    """An unstaged re-baseline from before the run is neither compared nor thrown away."""
    shot = repo / "shots" / "home-phone-dark.png"
    _png(shot, changes=200, delta=100)
    os.utime(shot, (time.time() - 600, time.time() - 600))
    since = time.time()
    _recapture(repo / "shots" / "home-phone-light.png")
    assert sb.run(repo, mode="check-tree", since=since) == sb.EXIT_PASS
    assert git_diff_names(repo) == ["shots/home-phone-dark.png"]


def test_deleted_shot_is_drift(repo: Path) -> None:
    (repo / "shots" / "home-phone-dark.png").unlink()
    since = time.time()
    _recapture(repo / "shots" / "home-phone-light.png")
    assert sb.run(repo, mode="check-tree", since=since) == sb.EXIT_DRIFT


def test_unreadable_recapture_is_not_confirmed(repo: Path) -> None:
    since = time.time()
    (repo / "shots" / "home-phone-light.png").write_bytes(b"truncated")
    assert sb.run(repo, mode="check-tree", since=since) == sb.EXIT_NOT_CONFIRMED


def test_no_committed_baseline_is_not_confirmed(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(_ENABLED, encoding="utf-8")
    _png(tmp_path / "shots" / "new-phone-light.png")
    assert sb.run(tmp_path, mode="check-tree", since=0.0) == sb.EXIT_NOT_CONFIRMED


def test_not_a_git_repo_is_not_confirmed(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text(_ENABLED, encoding="utf-8")
    assert sb.run(tmp_path, mode="check-tree", since=0.0) == sb.EXIT_NOT_CONFIRMED


def test_disabled_stage_passes_with_its_skip_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text("", encoding="utf-8")
    assert sb.run(tmp_path, mode="check-tree", since=0.0) == sb.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out


def test_bad_config_exits_2(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text("[shot_baseline]\nenabled = true\nbogus = 1\n", encoding="utf-8")
    assert sb.run(tmp_path, mode="check-tree", since=0.0) == sb.EXIT_CONFIG


# ------------------------------------------------------------ capture modes

def _capture_script(repo: Path, body: str) -> None:
    """Point `capture` at a tiny script that rewrites the shots the way an e2e run would."""
    (repo / "capture.py").write_text(body, encoding="utf-8")
    (repo / ".fleet.toml").write_text(_ENABLED + 'capture = ["capture.py"]\n', encoding="utf-8")


_REWRITE = (
    "from PIL import Image\n"
    "for name in ('home-phone-light.png', 'home-phone-dark.png'):\n"
    "    Image.new('RGB', (100, 100), (128, 128, 128)).save('shots/' + name)\n"
)


def test_baseline_mode_runs_the_capture_then_compares(repo: Path) -> None:
    _capture_script(repo, _REWRITE)
    assert sb.run(repo, mode="baseline") == sb.EXIT_PASS


def test_failed_capture_is_not_confirmed(repo: Path) -> None:
    _capture_script(repo, "raise SystemExit(4)\n")
    assert sb.run(repo, mode="baseline") == sb.EXIT_NOT_CONFIRMED


def test_two_run_mode_passes_on_a_reproducible_capture(repo: Path) -> None:
    _capture_script(repo, _REWRITE)
    assert sb.run(repo, mode="determinism") == sb.EXIT_PASS


def test_two_run_mode_fails_when_a_run_paints_something_else(repo: Path) -> None:
    # Something unpinned on screen: each run paints a different shade.
    _capture_script(repo, (
        "from pathlib import Path\nfrom PIL import Image\n"
        "runs = Path('runs.txt')\nn = int(runs.read_text()) if runs.exists() else 0\nruns.write_text(str(n + 1))\n"
        "Image.new('RGB', (100, 100), (n * 150, 0, 0)).save('shots/home-phone-light.png')\n"
    ))
    assert sb.run(repo, mode="determinism") == sb.EXIT_DRIFT
    git(repo, "diff", "--quiet", "--", "shots")


def test_cli_refuses_check_tree_without_since() -> None:
    with pytest.raises(SystemExit) as exc:
        sb.main(["--check-tree"])
    assert exc.value.code == 2


def git_diff_names(repo: Path) -> list[str]:
    return sb._git_paths(repo, "diff", "--name-only", "--", "shots")


def test_scaffold_adopts_the_stage_and_catalogs_both_halves() -> None:
    from scripts.vendored_catalog import load_catalog

    root = Path(__file__).resolve().parents[1]
    cfg = sb.load_config(root)
    assert cfg is not None and (root / cfg.shots_dir).is_dir()
    catalog = load_catalog()
    assert catalog["shot_baseline"]["src"] == "scripts/shot_baseline.py"
    assert catalog["shot_capture"]["src"] == "tests/e2e/_shot.py"
