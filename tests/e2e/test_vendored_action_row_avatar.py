"""The vendored `action-row` avatar keeps its 36px paint but meets the 44px hit floor.

The avatar sits inside the row's main button, so a tap on it already lands on the
row; the floor is what the design-lint touch-target check measures, and it comes
from an invisible `::before`, never from a bigger squircle.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import assert_min_target

_AVATARS = ("#demoAvatarUp", "#demoAvatarDown", "#demoAvatarPlain")


@pytest.mark.parametrize("avatar", _AVATARS)
def test_avatar_hit_box_reaches_44px_without_growing_the_paint(gallery: Page, avatar: str) -> None:
    assert_min_target(gallery.locator(avatar))
    assert _style(gallery, avatar, "width") == "36px"
    assert _style(gallery, avatar, "height") == "36px"


def test_avatar_hit_area_does_not_replace_the_badge(gallery: Page) -> None:
    """The badge is the `::after`; the hit area is the `::before`, so neither displaces the other."""
    badge = "(el) => getComputedStyle(el, '::after').content"
    assert gallery.eval_on_selector("#demoAvatarUp", badge) == '""'
    assert gallery.eval_on_selector("#demoAvatarPlain", badge) == "none"
