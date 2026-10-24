"""The screenshot baseline, proven on the scaffold's own component gallery.

`test_gallery_shots` is the capture the pre-ship gate compares: it writes the
gallery at phone and desktop, light and dark, into the committed baseline
folder, and `scripts/shot_baseline.py --check-tree` then compares those files
with git's copy and restores them.

The other two prove the comparison itself end to end, on real captures in a
throwaway git repo so the scaffold's own baseline is never touched: two
captures of the same commit compare clean (exit 0), and a deliberate visible
change to the page fails (exit 1) and is restored from the index.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page

from scripts import shot_baseline as sb
from tests._git_repo import git
from tests.e2e._shot import DESKTOP, PHONE, Variant, capture_screen

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.only_browser("chromium")

#: The two corners of the matrix: most pixels (phone, scale 3) and the other theme.
_PROOF_VARIANTS = (Variant(PHONE, "light"), Variant(DESKTOP, "dark"))


def _shots_dir() -> Path:
    cfg = sb.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold enables [shot_baseline] in .fleet.toml"
    return REPO_ROOT / cfg.shots_dir


def _gallery_ready(page: Page, variant: Variant) -> None:
    """The gallery's theme is an explicit `data-theme` toggle, not the media query alone."""
    page.wait_for_selector("body[data-demo-ready='1']")
    page.evaluate("(t) => { document.documentElement.dataset.theme = t; }", variant.theme)


def _visibly_changed(page: Page, variant: Variant) -> None:
    """The kind of slip a move-only refactor makes: one rule lost, so headings shift."""
    _gallery_ready(page, variant)
    page.add_style_tag(content="h1, h2 { letter-spacing: 2px; }")


def test_gallery_shots(browser: Browser, static_server: str) -> None:
    written = capture_screen(browser, f"{static_server}/_vendored/demo.html", "gallery", _shots_dir(),
                             prepare=_gallery_ready)
    assert [p.name for p in written] == [
        "gallery-phone-light.png", "gallery-phone-dark.png",
        "gallery-desktop-light.png", "gallery-desktop-dark.png",
    ]


@pytest.fixture(scope="module")
def baseline_repo(browser: Browser, static_server: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A throwaway repo whose index holds one capture of the gallery as its baseline."""
    root = tmp_path_factory.mktemp("shot-baseline-repo")
    git(root, "init", "-q")
    (root / ".fleet.toml").write_text('[shot_baseline]\nenabled = true\nshots_dir = "shots"\n', encoding="utf-8")
    capture_screen(browser, f"{static_server}/_vendored/demo.html", "gallery", root / "shots",
                   prepare=_gallery_ready, only=_PROOF_VARIANTS)
    git(root, "add", "-f", "shots")
    return root


def test_two_captures_of_the_same_commit_match(
    browser: Browser, static_server: str, baseline_repo: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    since = time.time()
    capture_screen(browser, f"{static_server}/_vendored/demo.html", "gallery", baseline_repo / "shots",
                   prepare=_gallery_ready, only=_PROOF_VARIANTS)
    assert sb.run(baseline_repo, mode="check-tree", since=since) == sb.EXIT_PASS
    assert "2 of 2 committed shot(s) recaptured, 0 drifted" in capsys.readouterr().out


def test_a_deliberate_visible_change_is_caught(
    browser: Browser, static_server: str, baseline_repo: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    since = time.time()
    capture_screen(browser, f"{static_server}/_vendored/demo.html", "gallery", baseline_repo / "shots",
                   prepare=_visibly_changed, only=_PROOF_VARIANTS)
    assert sb.run(baseline_repo, mode="check-tree", since=since) == sb.EXIT_DRIFT
    out = capsys.readouterr().out
    assert "DRIFTED: gallery-phone-light.png" in out and "DRIFTED: gallery-desktop-dark.png" in out
    # The run restored the baseline over the drifted capture (`git diff --quiet` raises otherwise).
    git(baseline_repo, "diff", "--quiet", "--", "shots")
