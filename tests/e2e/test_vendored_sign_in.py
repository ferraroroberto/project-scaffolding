"""Render and behaviour harness for the vendored `sign-in` sheet.

The real `sign-in.js` and `sign-in.css` run on the `demo.html` gallery, which
carries the tokens, the icons sprite and the modal, button and select-native
recipes the sheet builds on. The app's login route is a Playwright route the
test answers, so each server reply (token, 401, 429, 503, a dropped
connection, a slow answer) is driven exactly.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from playwright.sync_api import Page, Route, expect

from tests.e2e._cases import cases
from tests.e2e._color_assertions import set_theme, style

_ENDPOINT = "/api/login"
_DIALOG = "dialog.sign-in"
_INPUT = f"{_DIALOG} .sign-in-input"
_SUBMIT = f"{_DIALOG} .sign-in-submit"
_ERROR = f"{_DIALOG} .sign-in-error"

# Light / dark `--danger-text` from the gallery's token blocks (design.md, design.dark.md).
_DANGER_TEXT = {"light": "rgb(164, 14, 38)", "dark": "rgb(255, 123, 114)"}

_OPEN = """
async (endpoint) => {
  await new Promise((resolve) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'sign-in/sign-in.css';
    link.onload = resolve;
    document.head.appendChild(link);
  });
  const { requestSignIn } = await import('./sign-in/sign-in.js');
  window.__tokens = [];
  window.__storageBefore = localStorage.length;
  const opts = { endpoint, hint: 'Enter the password to use the app.',
                 onToken: (t) => { window.__tokens.push(t); } };
  window.__first = requestSignIn(opts);
  window.__second = requestSignIn(opts);
  window.__same = window.__first === window.__second;
  window.__first.then((t) => { window.__resolved = t; });
}
"""


def _answer(page: Page, reply: Callable[[Route], None]) -> list[dict[str, object]]:
    """Answer the login route with `reply`, recording every request body."""
    bodies: list[dict[str, object]] = []

    def handle(route: Route) -> None:
        bodies.append(route.request.post_data_json)
        reply(route)

    page.route(f"**{_ENDPOINT}", handle)
    return bodies


def _open(page: Page) -> None:
    page.evaluate(_OPEN, _ENDPOINT)
    expect(page.locator(_DIALOG)).to_be_visible()


def _submit(page: Page, password: str = "hunter2") -> None:
    page.fill(_INPUT, password)
    page.click(_SUBMIT)


def _check_the_sheet_renders_one_field_one_primary_and_no_close(gallery: Page) -> None:
    _open(gallery)
    dialog = gallery.locator(_DIALOG)
    assert dialog.get_attribute("data-track-view") == "sign-in"
    assert gallery.evaluate("document.querySelector('dialog.sign-in').parentElement === document.body")
    expect(dialog.locator(".sign-in-title")).to_have_text("Sign in")
    expect(dialog.locator(".sign-in-hint")).to_have_text("Enter the password to use the app.")
    expect(dialog.locator(".detail-close")).to_have_count(0)
    assert dialog.locator("input").count() == 1
    assert gallery.get_attribute(_INPUT, "type") == "password"
    assert gallery.get_attribute(_INPUT, "autocomplete") == "current-password"
    assert gallery.get_attribute(_SUBMIT, "data-track") == "sign-in-submit"
    assert gallery.evaluate("document.activeElement.classList.contains('sign-in-input')")
    assert gallery.evaluate("window.__same"), "a second call while open must share the one prompt"

    expect(gallery.locator(_SUBMIT)).to_be_disabled()
    gallery.fill(_INPUT, "x")
    expect(gallery.locator(_SUBMIT)).to_be_enabled()

    field = gallery.locator(_INPUT).bounding_box()
    primary = gallery.locator(_SUBMIT).bounding_box()
    assert field is not None and primary is not None
    assert abs(field["width"] - primary["width"]) < 1, "field and primary both fill the card"
    assert primary["height"] == 48, "the footer primary is the modal's 48px button-primary"


def _check_escape_does_not_dismiss_the_sheet(gallery: Page) -> None:
    _open(gallery)
    gallery.keyboard.press("Escape")
    gallery.keyboard.press("Escape")
    expect(gallery.locator(_DIALOG)).to_be_visible()


def _check_a_wrong_password_says_so_and_selects_the_field(gallery: Page, theme: str) -> None:
    set_theme(gallery, theme)
    bodies = _answer(gallery, lambda r: r.fulfill(status=401, json={"detail": "bad password"}))
    _open(gallery)
    _submit(gallery)
    expect(gallery.locator(_ERROR)).to_have_text("Wrong password")
    assert bodies == [{"password": "hunter2"}]
    assert style(gallery, _ERROR, "color") == _DANGER_TEXT[theme]
    assert gallery.evaluate(
        "(() => { const i = document.querySelector('.sign-in-input');"
        " return document.activeElement === i && i.selectionStart === 0 && i.selectionEnd === i.value.length; })()"
    )
    expect(gallery.locator(_SUBMIT)).to_have_text("Sign in")
    expect(gallery.locator(_SUBMIT)).to_be_enabled()


# Each refusal the server can answer with, by name: status, headers, the one message shown.
_REFUSALS = [
    ("lockout", 429, {"Retry-After": "30"}, "Too many attempts — try again in 30 s"),
    ("lockout-no-retry-after", 429, {}, "Too many attempts — try again later"),
    ("not-set-up", 503, {}, "Password sign-in isn't set up on this server"),
    ("other", 500, {}, "Sign-in failed (HTTP 500)"),
]


def _check_each_server_refusal_has_its_one_message(
    gallery: Page, status: int, headers: dict[str, str], message: str
) -> None:
    _answer(gallery, lambda r: r.fulfill(status=status, headers=headers, json={"detail": "server words"}))
    _open(gallery)
    _submit(gallery)
    expect(gallery.locator(_ERROR)).to_have_text(message)
    expect(gallery.locator(_DIALOG)).to_be_visible()


def _check_an_unreachable_server_says_so(gallery: Page) -> None:
    _answer(gallery, lambda r: r.abort("connectionrefused"))
    _open(gallery)
    _submit(gallery)
    expect(gallery.locator(_ERROR)).to_have_text("Can't reach the app")


def _check_the_primary_is_busy_while_the_request_is_pending(gallery: Page) -> None:
    held: list[Route] = []
    _answer(gallery, held.append)
    _open(gallery)
    _submit(gallery)
    expect(gallery.locator(_SUBMIT)).to_have_text("Signing in…")
    expect(gallery.locator(_SUBMIT)).to_be_disabled()
    assert gallery.get_attribute(_SUBMIT, "aria-busy") == "true"
    gallery.wait_for_function("document.querySelector('.sign-in-input').readOnly")
    held[0].fulfill(status=401, json={})
    expect(gallery.locator(_SUBMIT)).to_have_text("Sign in")
    assert gallery.get_attribute(_SUBMIT, "aria-busy") == "false"


def _check_success_hands_the_token_over_closes_and_stores_nothing(gallery: Page) -> None:
    _answer(gallery, lambda r: r.fulfill(status=200, json={"token": "tok-123"}))
    _open(gallery)
    _submit(gallery)
    gallery.wait_for_function("window.__resolved === 'tok-123'")
    expect(gallery.locator(_DIALOG)).to_be_hidden()
    assert gallery.evaluate("window.__tokens") == ["tok-123"]
    assert gallery.evaluate("localStorage.length === window.__storageBefore"), "the component never stores the token"
    assert gallery.evaluate("document.querySelector('.sign-in-input').value") == ""


def test_sign_in_sheet_contract(new_gallery: Callable[[], AbstractContextManager[Page]]) -> None:
    """The sign-in sheet: its shape, each server answer's one message, the busy state and the token hand-over."""
    with cases() as c:
        with c.case("the_sheet_renders_one_field_one_primary_and_no_close"), new_gallery() as gallery:
            _check_the_sheet_renders_one_field_one_primary_and_no_close(gallery=gallery)
        with c.case("escape_does_not_dismiss_the_sheet"), new_gallery() as gallery:
            _check_escape_does_not_dismiss_the_sheet(gallery=gallery)
        for theme in ["light", "dark"]:
            with c.case(f"a_wrong_password_says_so_and_selects_the_field[{theme}]"), new_gallery() as gallery:
                _check_a_wrong_password_says_so_and_selects_the_field(gallery=gallery, theme=theme)
        for refusal, status, headers, message in _REFUSALS:
            with c.case(f"each_server_refusal_has_its_one_message[{refusal}]"), new_gallery() as gallery:
                _check_each_server_refusal_has_its_one_message(gallery=gallery, status=status, headers=headers, message=message)
        with c.case("an_unreachable_server_says_so"), new_gallery() as gallery:
            _check_an_unreachable_server_says_so(gallery=gallery)
        with c.case("the_primary_is_busy_while_the_request_is_pending"), new_gallery() as gallery:
            _check_the_primary_is_busy_while_the_request_is_pending(gallery=gallery)
        with c.case("success_hands_the_token_over_closes_and_stores_nothing"), new_gallery() as gallery:
            _check_success_hands_the_token_over_closes_and_stores_nothing(gallery=gallery)
