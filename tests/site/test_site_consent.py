"""The `site-consent` bar: first visit, Accept, Reject, reopen, stored choice, and no network.

The component runs under Node through its probe against stubbed browser globals (a cookie
jar, an event bus, two buttons and an opener link). Node is part of the gate's toolchain,
so its absence fails here rather than skipping.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPONENT = REPO_ROOT / "app" / "site" / "static" / "_vendored" / "site-consent"
MODULE = COMPONENT / "site-consent.js"
PROBE = Path(__file__).resolve().parent / "_site_consent_probe.mjs"


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the site-consent tests"
    done = subprocess.run(
        [node, "--no-warnings", str(PROBE), str(MODULE)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_the_bar_shows_on_a_first_visit_without_storing_or_taking_focus(probe: dict[str, Any]) -> None:
    first = probe["first"]
    assert first == {"shown": True, "writes": 0, "events": 0, "focused": 0, "reserve": "64px", "consent": None}


def test_accept_stores_the_choice_hides_the_bar_and_fires_the_event(probe: dict[str, Any]) -> None:
    accept = probe["accept"]
    assert accept["shown"] is False and accept["consent"] is True and accept["reserve"] is None
    assert accept["events"] == [{"granted": True}]
    [write] = accept["writes"]
    assert re.fullmatch(r"consent=granted; Max-Age=15811200; Path=/; SameSite=Lax; Secure", write)


def test_reject_stores_the_choice_hides_the_bar_and_fires_the_event(probe: dict[str, Any]) -> None:
    reject = probe["reject"]
    assert reject["shown"] is False and reject["consent"] is False
    assert reject["events"] == [{"granted": False}]
    assert reject["writes"][0].startswith("consent=denied; Max-Age=15811200;")


def test_a_stored_choice_suppresses_the_bar_and_announces_nothing(probe: dict[str, Any]) -> None:
    assert probe["afterAccept"] == {"shown": False, "writes": 0, "events": 0, "consent": True}


def test_the_open_link_reopens_the_bar_and_one_reject_withdraws(probe: dict[str, Any]) -> None:
    assert probe["reopen"] == {"shown": True, "prevented": True, "barFocused": 1}
    withdraw = probe["withdraw"]
    assert withdraw["shown"] is False and withdraw["consent"] is False
    assert withdraw["events"] == [{"granted": False}]
    assert withdraw["openerFocused"] == 1


def test_repeating_the_stored_choice_renews_the_cookie_but_announces_nothing(probe: dict[str, Any]) -> None:
    assert probe["sameChoice"] == {"writes": 1, "events": 0, "shown": False}


def test_escape_closes_a_reopened_bar_unchanged_but_not_a_first_visit_bar(probe: dict[str, Any]) -> None:
    assert probe["escape"] == {"shown": False, "writes": 0, "events": 0}
    assert probe["firstEscape"] == {"shown": True}


def test_cookie_name_and_lifetime_are_attributes_and_plain_http_omits_secure(probe: dict[str, Any]) -> None:
    assert probe["custom"]["writes"] == ["cc=granted; Max-Age=2592000; Path=/; SameSite=Lax"]


def test_a_malformed_or_foreign_cookie_is_no_choice(probe: dict[str, Any]) -> None:
    assert probe["junk"] == {"shown": True, "consent": None}
    assert probe["otherCookie"] == {"shown": True, "consent": None}


def test_an_invalid_option_keeps_the_bar_hidden_and_warns(probe: dict[str, Any]) -> None:
    assert probe["invalid"] == {"shown": False, "daysShown": False, "consent": None, "warns": 2}


def test_without_a_bar_in_the_markup_nothing_happens(probe: dict[str, Any]) -> None:
    assert probe["noBar"] == {"consent": None, "writes": 0}


def test_the_component_makes_no_network_request(probe: dict[str, Any]) -> None:
    assert probe["network"] == 0
    source = MODULE.read_text(encoding="utf-8")
    assert not re.search(r"\b(fetch|XMLHttpRequest|sendBeacon|WebSocket|EventSource|import\()", source)
    assert "http://" not in source and "https://" not in source.replace("'https:'", "")


def test_the_stylesheet_uses_tokens_and_no_motion_or_modal_machinery() -> None:
    css = (COMPONENT / "site-consent.css").read_text(encoding="utf-8")
    assert "var(--ink)" in css and "var(--paper)" in css and "focus-visible" in css
    assert "backdrop-filter" not in css and "animation" not in css and "transition" not in css
    assert "inert" not in css and "overlay" not in css
    # Hex colours are the token file's job; the bar takes every colour from a token.
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css.split("*/", 1)[1])
