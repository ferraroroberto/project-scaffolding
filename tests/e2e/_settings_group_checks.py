"""Checks for the native select and the settings-group component.

Each check takes a freshly loaded `demo.html` gallery; `test_vendored_components.py`
runs them as cases. A select has two shapes: the bordered `select-native` form
control, and inside a Settings row the borderless muted value. The settings-group
checks pin the full Settings page: the page shell (full screen on a phone, a
centred column on desktop), the inset groups and their sentence-case labels at
the trial's measured edges, the separators and trailing edge, the detail sheet
fitting both phone heights, and what the hand-built Settings panes got wrong at
390px (labels that wrapped, values drawn as bordered pills, number fields of
different widths and sizes).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from playwright.sync_api import Page, Playwright, expect

from tests.e2e._cases import Cases
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import assert_no_horizontal_overflow
from tests.e2e.conftest import load_gallery

_PHONE = {"width": 390, "height": 844}


def _gap(gallery: Page, head: str, card: str) -> float:
    """Pixels between the bottom of a header and the top of its card (negative = overlap)."""
    return float(
        gallery.evaluate(
            "([h, c]) => document.querySelector(c).getBoundingClientRect().top"
            " - document.querySelector(h).getBoundingClientRect().bottom",
            [head, card],
        )
    )


def _lines(gallery: Page, selector: str) -> int:
    """How many line boxes an element's text occupies."""
    return int(
        gallery.evaluate(
            "(s) => { const r = document.createRange(); r.selectNodeContents(document.querySelector(s));"
            " return new Set([...r.getClientRects()].filter(q => q.width > 1).map(q => Math.round(q.top))).size; }",
            selector,
        )
    )


def check_select_native_contract(gallery: Page) -> None:
    """select-native: a 44px box (explicit height, not min-height) around a 36px visible control, control-border ring, input-bg fill."""
    # THE iOS decision: height is an explicit `height` (respected), never
    # `min-height` (ignored on a bare <select>, rendering it stubby).
    assert _style(gallery, "#demoSelectNative", "height") == "44px"
    assert _style(gallery, "#demoSelectNative", "borderTopLeftRadius").startswith("12px")
    # --control-border is drawn as an inset ring, not a border (the border is the transparent band).
    assert _style(gallery, "#demoSelectNative", "boxShadow") == "rgb(129, 139, 152) 0px 0px 0px 1px inset"
    # input-bg is card-off in light (var(--card-off) = #f6f8fa).
    assert _style(gallery, "#demoSelectNative", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoSelectNative", "color") == "rgb(31, 35, 40)"


def _assert_native_box(page: Page, sel: str) -> None:
    """One native control: a 44px box whose visible control (the padding box) is 36px."""
    box, visible = page.evaluate(
        "(s) => { const e = document.querySelector(s), c = getComputedStyle(e), h = e.getBoundingClientRect().height;"
        " return [h, h - parseFloat(c.borderTopWidth) - parseFloat(c.borderBottomWidth)]; }",
        sel,
    )
    assert box >= 44, (sel, box)
    assert visible == 36, (sel, visible)


def _add_demo_input(page: Page) -> None:
    """The gallery's only `.input-native` sits in a closed dialog, so a probe input goes beside the select."""
    page.evaluate(
        "() => { const i = document.createElement('input'); i.className = 'input-native'; i.id = 'probeInputNative';"
        " i.type = 'text'; document.querySelector('#demoSelectNative').after(i); }"
    )


def check_select_native_meets_the_hit_floor(gallery: Page) -> None:
    """select-native: the select and the shared `.input-native` are 44px at a fine and a coarse pointer, visible control 36px."""
    assert gallery.evaluate("matchMedia('(pointer: fine)').matches"), "fine-pointer run expected"
    _add_demo_input(gallery)
    for sel in ("#demoSelectNative", "#probeInputNative"):
        _assert_native_box(gallery, sel)
    context = gallery.context.browser.new_context(viewport=_PHONE, has_touch=True, is_mobile=True)
    try:
        phone = context.new_page()
        phone.goto(gallery.url)
        phone.wait_for_selector("body[data-demo-ready='1']")
        assert phone.evaluate("matchMedia('(pointer: coarse)').matches"), "coarse-pointer emulation is not active"
        _add_demo_input(phone)
        for sel in ("#demoSelectNative", "#probeInputNative"):
            _assert_native_box(phone, sel)
    finally:
        context.close()


def check_select_native_boundary_renders_in_webkit(playwright: Playwright, base_url: str) -> None:
    """select-native: in WebKit the ring is the control-border inset shadow, not the native menulist, with the chevron drawn."""
    browser = playwright.webkit.launch()
    try:
        context = browser.new_context(viewport=_PHONE, has_touch=True, is_mobile=True)
        page = load_gallery(context.new_page(), base_url)
        _assert_native_box(page, "#demoSelectNative")
        # --control-border is drawn as an inset ring; a WebKit native menulist computes it as `none`.
        assert _style(page, "#demoSelectNative", "boxShadow") == "rgb(129, 139, 152) 0px 0px 0px 1px inset"
        assert _style(page, "#demoSelectNative", "appearance") == "none"
        assert "linear-gradient" in _style(page, "#demoSelectNative", "backgroundImage"), "the chevron is missing"
    finally:
        browser.close()


def _open_page(gallery: Page, viewport: dict[str, int] = _PHONE) -> None:
    """Size the window, then open the Settings page the way the gear does."""
    gallery.set_viewport_size(viewport)
    gallery.locator("#openSettingsPage").click()
    expect(gallery.locator("#demoSettingsPage")).to_be_visible()


def _box(page: Page, selector: str) -> tuple[float, float, float, float]:
    """An element's (left, top, right, bottom) in viewport pixels."""
    b = page.evaluate(
        "(s) => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }",
        selector,
    )
    return float(b[0]), float(b[1]), float(b[2]), float(b[3])


def _separator(page: Page, selector: str) -> tuple[float, float, float]:
    """A row's separator (its ::before) as (left, right, height) in viewport pixels."""
    s = page.evaluate(
        "(s) => { const e = document.querySelector(s), b = e.getBoundingClientRect(), c = getComputedStyle(e, '::before');"
        " return [b.left + parseFloat(c.left), b.right - parseFloat(c.right), parseFloat(c.height)]; }",
        selector,
    )
    return float(s[0]), float(s[1]), float(s[2])


def check_settings_group_page_fills_the_phone(gallery: Page) -> None:
    """settings-group: the page is a full-screen dialog on a phone, its header the app header's colour, close on the content edge."""
    _open_page(gallery)
    left, top, right, bottom = _box(gallery, "#demoSettingsPage")
    assert (left, top, right, bottom) == (0, 0, 390, 844), (left, top, right, bottom)
    assert _style(gallery, ".settings-page-head", "backgroundColor") == _style(gallery, "body", "backgroundColor")
    # Title and close glyph on the content edges (inset 20 + padding 16).
    assert _box(gallery, "#demoSettingsTitle")[0] == 36
    assert _box(gallery, "#demoSettingsClose .icon")[2] == 354
    assert gallery.evaluate(
        "() => { const d = document.querySelector('#demoSettingsPage'); return d.scrollWidth <= d.clientWidth; }"
    ), "the page scrolls sideways"
    gallery.locator("#demoSettingsClose").click()
    expect(gallery.locator("#demoSettingsPage")).to_be_hidden()


def check_settings_group_page_is_a_centred_column_on_desktop(gallery: Page) -> None:
    """settings-group: at 1440 the groups sit in a centred column at the layout measure."""
    _open_page(gallery, {"width": 1440, "height": 900})
    left, _, right, _ = _box(gallery, "#demoSettingsGroup")
    assert (left, right) == (354, 1086), (left, right)  # 772 measure, 20px inset each side
    assert _box(gallery, "#demoSettingsHead")[0] == 370
    assert _box(gallery, "#demoSettingsClose .icon")[2] == 1070
    # Every trailing item ends on the card's inner edge, a select included.
    for sel in ("#demoSettingsLink .settings-row-chevron", "#demoSettingsPick .settings-row-chevron", "#demoSettingsSwitch"):
        assert _box(gallery, sel)[2] == 1070, sel


def check_settings_group_label_sits_above_its_card(gallery: Page) -> None:
    """settings-group: the label is sentence case 16px/700 muted, outside its card with a positive gap, at every text size."""
    _open_page(gallery)
    head = "#demoSettingsHead"
    assert _style(gallery, head, "textTransform") == "none"
    assert _style(gallery, head, "letterSpacing") in ("normal", "0px")
    assert _style(gallery, head, "fontSize") == "16px"
    assert _style(gallery, head, "fontWeight") == "700"
    assert _style(gallery, head, "color") == "rgb(101, 109, 118)"  # --muted
    assert _box(gallery, head)[0] == 36
    # The label is not inside the card it names; groups are about 30px apart.
    assert gallery.locator("#demoSettingsGroup #demoSettingsHead").count() == 0
    assert _box(gallery, "#demoSettingsHead2")[1] - _box(gallery, "#demoSettingsFootnote")[3] == 30
    for root_px in ("16px", "18px", "20px"):
        gallery.evaluate("(px) => { document.documentElement.style.fontSize = px; }", root_px)
        for h, c in (("#demoSettingsHead", "#demoSettingsGroup"), ("#demoSettingsHead2", "#demoSettingsGroup2")):
            gap = _gap(gallery, h, c)
            assert gap >= 4, f"{h} is {gap}px from its card at a {root_px} root"
        assert _lines(gallery, "#demoSettingsSwitchRow .settings-row-label") == 1
    assert_no_horizontal_overflow(gallery)


def check_settings_group_rows_and_value(gallery: Page) -> None:
    """settings-group: a borderless 20px-radius card inset 20px, 52px rows, separators title-to-edge, a muted unboxed value."""
    _open_page(gallery)
    group = "#demoSettingsGroup"
    left, _, right, _ = _box(gallery, group)
    assert (left, right) == (20, 370), (left, right)
    assert _style(gallery, group, "borderTopLeftRadius") == "20px"
    assert _style(gallery, group, "borderTopWidth") == "0px"
    assert _style(gallery, group, "paddingTop") == "0px"
    assert _style(gallery, group, "overflow") == "hidden"
    box = gallery.locator("#demoSettingsLink").bounding_box()
    assert box is not None and box["height"] >= 52, box
    assert _box(gallery, "#demoSettingsLink .settings-row-icon")[0] == 36
    # Separators: none above the first row; the next one runs from its title
    # (past the glyph) to the inner edge, a glyph-less row's from its label.
    assert gallery.evaluate(
        "() => getComputedStyle(document.querySelector('#demoSettingsLink'), '::before').content"
    ) == "none"
    sep_left, sep_right, sep_h = _separator(gallery, "#demoSettingsLong")
    assert (sep_left, sep_right, sep_h) == (_box(gallery, "#demoSettingsLongLabel")[0], 354, 1), (sep_left, sep_right)
    assert _separator(gallery, "#demoSettingsPlainRow")[:2] == (36, 354)
    assert gallery.evaluate(
        "() => getComputedStyle(document.querySelector('#demoSettingsLong'), '::before').backgroundColor"
    ) == "rgb(216, 222, 228)"
    # Every trailing item ends on the inner edge, symmetric with the left.
    for sel in (
        "#demoSettingsLink .settings-row-chevron",
        "#demoSettingsPick .settings-row-chevron",
        "#demoSettingsSwitch",
        "#demoSettingsNumberRow .settings-row-unit",
        "#demoSettingsSwitch2",
    ):
        assert _box(gallery, sel)[2] == 354, sel
    assert _style(gallery, "#demoSettingsLink .settings-row-icon", "width") == "18px"
    assert _style(gallery, "#demoSettingsLink .settings-row-chevron", "width") == "16px"
    # The value is muted text, never a bordered pill.
    assert _style(gallery, "#demoSettingsValue", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoSettingsValue", "fontSize") == "14px"
    assert _style(gallery, "#demoSettingsValue", "borderTopWidth") == "0px"
    # A long value ellipsizes first; the label stays whole on one line.
    assert gallery.evaluate(
        "() => { const v = document.querySelector('#demoSettingsLongValue'); return v.scrollWidth > v.clientWidth; }"
    )
    assert gallery.evaluate(
        "() => { const l = document.querySelector('#demoSettingsLongLabel'); return l.scrollWidth <= l.clientWidth; }"
    )
    assert _style(gallery, "#demoSettingsToneValue", "color") == "rgb(125, 78, 0)"  # --attention-text
    # The hint line under a label is muted and single-line.
    assert _style(gallery, "#demoSettingsHint", "color") == "rgb(101, 109, 118)"
    assert _lines(gallery, "#demoSettingsHint") == 1


def check_settings_group_select_is_the_muted_value(gallery: Page) -> None:
    """settings-group: a select in a row is drawn as the value (borderless, muted, full-height target)."""
    _open_page(gallery)
    sel = "#demoSettingsSelect"
    assert _style(gallery, sel, "borderTopWidth") == "0px"
    assert _style(gallery, sel, "backgroundColor") == "rgba(0, 0, 0, 0)"
    assert _style(gallery, sel, "color") == "rgb(101, 109, 118)"
    assert _style(gallery, sel, "fontSize") == "14px"
    assert _style(gallery, sel, "height") == "44px"
    assert _style(gallery, sel, "appearance") == "none"


def check_settings_group_switch_row_toggles_from_the_row(gallery: Page) -> None:
    """settings-group: the switch row is a label, so a tap on its text toggles the switch."""
    _open_page(gallery)
    switch = gallery.locator("#demoSettingsSwitch")
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(switch).to_have_accessible_name("Translate to English Any language in, English out")
    gallery.locator("#demoSettingsSwitchRow .settings-row-label").click()
    expect(gallery.locator("#demoSettingsSwitch")).to_have_attribute("aria-checked", "true")
    gallery.locator("#demoSettingsSwitch").click()
    expect(gallery.locator("#demoSettingsSwitch")).to_have_attribute("aria-checked", "false")


def check_settings_group_number_fields_are_one_shape(gallery: Page) -> None:
    """settings-group: every number field is 80px, 16px text (no iOS zoom), right-aligned figures."""
    for sel in ("#demoSettingsNumber", "#demoSettingsNumber2"):
        assert _style(gallery, sel, "width") == "80px", sel
        assert _style(gallery, sel, "fontSize") == "16px", sel
        assert _style(gallery, sel, "textAlign") == "right", sel
        assert _style(gallery, sel, "fontVariantNumeric") == "tabular-nums", sel
        # --control-border is drawn as an inset ring, not a border (the border is the transparent band).
        assert _style(gallery, sel, "boxShadow") == "rgb(129, 139, 152) 0px 0px 0px 1px inset", sel
    assert _style(gallery, "#demoSettingsNumberRow .settings-row-unit", "color") == "rgb(101, 109, 118)"


def _assert_number_field_box(page: Page, sel: str) -> None:
    """One number field: a 44px box whose visible control (the padding box) is 36px."""
    box, visible = page.evaluate(
        "(s) => { const e = document.querySelector(s), c = getComputedStyle(e), h = e.getBoundingClientRect().height;"
        " return [h, h - parseFloat(c.borderTopWidth) - parseFloat(c.borderBottomWidth)]; }",
        sel,
    )
    assert box >= 44, (sel, box)
    assert visible == 36, (sel, visible)


def check_settings_group_number_field_meets_the_hit_floor(gallery: Page) -> None:
    """settings-group: the number field's box is 44px at a fine and a coarse pointer, its visible control 36px."""
    assert gallery.evaluate("matchMedia('(pointer: fine)').matches"), "fine-pointer run expected"
    _open_page(gallery)
    for sel in ("#demoSettingsNumber", "#demoSettingsNumber2"):
        _assert_number_field_box(gallery, sel)
    context = gallery.context.browser.new_context(viewport=_PHONE, has_touch=True, is_mobile=True)
    try:
        phone = context.new_page()
        phone.goto(gallery.url)
        phone.wait_for_selector("body[data-demo-ready='1']")
        assert phone.evaluate("matchMedia('(pointer: coarse)').matches"), "coarse-pointer emulation is not active"
        _open_page(phone)
        for sel in ("#demoSettingsNumber", "#demoSettingsNumber2"):
            _assert_number_field_box(phone, sel)
    finally:
        context.close()


def check_settings_group_sheet_fits_both_phone_heights(gallery: Page) -> None:
    """settings-group: a detail sheet fits the viewport at 844 and 664, title and Done pinned, the body scrolling."""
    for height in (844, 664):
        _open_page(gallery, {"width": 390, "height": height})
        gallery.locator("#demoSettingsLink").click()
        expect(gallery.locator("#demoSettingsSheet")).to_be_visible()
        top, bottom = _box(gallery, "#demoSettingsSheet")[1::2]
        assert top >= 0 and bottom <= height, (height, top, bottom)
        assert gallery.evaluate(
            "() => { const b = document.querySelector('#demoSettingsSheetBody'); return b.scrollHeight > b.clientHeight; }"
        ), f"the sheet body does not scroll at {height}"
        gallery.evaluate("() => { document.querySelector('#demoSettingsSheetBody').scrollTop = 1e6; }")
        for sel in ("#demoSettingsSheetClose", "#demoSettingsSheetDone"):
            s_top, s_bottom = _box(gallery, sel)[1::2]
            assert s_top >= top and s_bottom <= bottom, (height, sel, s_top, s_bottom)
        expect(gallery.locator("#demoSettingsSheetDone")).to_be_in_viewport(ratio=1)
        expect(gallery.locator("#demoSettingsSheetClose")).to_be_in_viewport(ratio=1)
        gallery.locator("#demoSettingsSheetDone").click()
        expect(gallery.locator("#demoSettingsSheet")).to_be_hidden()
        gallery.locator("#demoSettingsClose").click()


def check_settings_group_dark(gallery: Page) -> None:
    """settings-group: the dark theme re-skins label, value, separator, canvas and field from the tokens."""
    _set_theme(gallery, "dark")
    _open_page(gallery)
    assert _style(gallery, "#demoSettingsHead", "color") == "rgb(125, 133, 144)"
    assert _style(gallery, "#demoSettingsValue", "color") == "rgb(125, 133, 144)"
    assert gallery.evaluate(
        "() => getComputedStyle(document.querySelector('#demoSettingsLong'), '::before').backgroundColor"
    ) == "rgb(33, 38, 45)"
    assert _style(gallery, "#demoSettingsGroup", "backgroundColor") == "rgb(22, 27, 34)"
    # The canvas sits a step under the cards: the app canvas in dark.
    assert _style(gallery, "#demoSettingsPage", "backgroundColor") == "rgb(13, 17, 23)"
    assert _style(gallery, ".settings-page-head", "backgroundColor") == "rgb(13, 17, 23)"
    assert _style(gallery, "#demoSettingsNumber", "backgroundColor") == "rgb(33, 38, 45)"
    assert _style(gallery, "#demoSettingsToneValue", "color") == "rgb(227, 179, 65)"


_CHECKS = (
    check_settings_group_page_fills_the_phone,
    check_settings_group_page_is_a_centred_column_on_desktop,
    check_settings_group_label_sits_above_its_card,
    check_settings_group_rows_and_value,
    check_settings_group_select_is_the_muted_value,
    check_settings_group_switch_row_toggles_from_the_row,
    check_settings_group_number_fields_are_one_shape,
    check_settings_group_number_field_meets_the_hit_floor,
    check_settings_group_sheet_fits_both_phone_heights,
    check_select_native_meets_the_hit_floor,
    check_settings_group_dark,
)


def run_settings_group_cases(c: Cases, new_gallery: Callable[[], AbstractContextManager[Page]]) -> None:
    """Run every settings-group check as its own case, each on a freshly loaded gallery."""
    for check in _CHECKS:
        with c.case(check.__name__.removeprefix("check_")), new_gallery() as gallery:
            check(gallery)
