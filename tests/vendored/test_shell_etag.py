"""``src/shell_etag.py`` answers shell revalidation once, for every app."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from src.compression import StreamSafeGZipMiddleware
from src.shell_etag import (
    SHELL_CACHE_CONTROL,
    etag_for,
    etag_matches,
    shell_response,
)

SHELL_V1 = "<!doctype html><script src='/static/main.js?v=aaaa1111'></script>" + (
    "<p>fleet shell</p>" * 120
)
SHELL_V2 = SHELL_V1.replace("aaaa1111", "bbbb2222")


def _client(shell: dict[str, str], *, gzip: bool = False) -> TestClient:
    async def index(request: Request) -> Response:
        return shell_response(request, shell["html"])

    app = Starlette(routes=[Route("/", index)])
    if gzip:
        app.add_middleware(StreamSafeGZipMiddleware)
    return TestClient(app)


# ------------------------------------------------------------------ the tag


def test_the_tag_is_weak_and_stable() -> None:
    tag = etag_for(SHELL_V1)

    assert tag.startswith('W/"') and tag.endswith('"')
    assert etag_for(SHELL_V1) == tag
    assert etag_for(SHELL_V1.encode("utf-8")) == tag  # str and bytes agree


def test_a_changed_build_gives_a_new_tag() -> None:
    assert etag_for(SHELL_V1) != etag_for(SHELL_V2)


# ------------------------------------------------------ If-None-Match parsing


@pytest.mark.parametrize(
    "header",
    [
        "{tag}",  # exact
        "{opaque}",  # strong form of a weak tag: weak comparison
        '"other", {tag}',  # a list, ours last
        '{tag}, "other"',  # a list, ours first
        '"a" ,  {tag}  , W/"b"',  # stray whitespace
        "*",
        "  *  ",
    ],
)
def test_a_matching_header_revalidates(header: str) -> None:
    tag = etag_for(SHELL_V1)

    assert etag_matches(header.format(tag=tag, opaque=tag.removeprefix("W/")), tag)


@pytest.mark.parametrize(
    "header",
    [None, "", "   ", '"other"', 'W/"other", "also"', "garbage", "W/", '"unterminated'],
)
def test_anything_else_gets_the_full_body(header: str | None) -> None:
    assert not etag_matches(header, etag_for(SHELL_V1))


# --------------------------------------------------------------- the response


def test_a_first_load_is_a_full_200_with_the_policy_and_tag() -> None:
    client = _client({"html": SHELL_V1})

    response = client.get("/")

    assert response.status_code == 200
    assert response.text == SHELL_V1
    assert response.headers["cache-control"] == SHELL_CACHE_CONTROL == (
        "no-cache, must-revalidate"
    )
    assert response.headers["etag"] == etag_for(SHELL_V1)
    assert response.headers["content-type"] == "text/html; charset=utf-8"


def test_a_matching_revalidation_is_a_bodiless_304_that_keeps_the_headers() -> None:
    client = _client({"html": SHELL_V1})
    tag = client.get("/").headers["etag"]

    revalidated = client.get("/", headers={"If-None-Match": tag})

    assert revalidated.status_code == 304
    assert revalidated.content == b""
    assert revalidated.headers["cache-control"] == SHELL_CACHE_CONTROL
    assert revalidated.headers["etag"] == tag


def test_a_mismatch_gets_the_full_200() -> None:
    client = _client({"html": SHELL_V1})

    response = client.get("/", headers={"If-None-Match": 'W/"stale"'})

    assert response.status_code == 200
    assert response.text == SHELL_V1


def test_a_star_and_a_list_revalidate() -> None:
    client = _client({"html": SHELL_V1})
    tag = client.get("/").headers["etag"]

    assert client.get("/", headers={"If-None-Match": "*"}).status_code == 304
    listed = client.get("/", headers={"If-None-Match": f'"x", {tag}'})
    assert listed.status_code == 304


def test_a_rebuilt_shell_is_never_pinned_by_the_old_tag() -> None:
    shell = {"html": SHELL_V1}
    client = _client(shell)
    old_tag = client.get("/").headers["etag"]
    shell["html"] = SHELL_V2  # a deploy restamps the asset URLs

    after_deploy = client.get("/", headers={"If-None-Match": old_tag})

    assert after_deploy.status_code == 200
    assert after_deploy.text == SHELL_V2
    assert after_deploy.headers["etag"] != old_tag
    assert client.get(
        "/", headers={"If-None-Match": after_deploy.headers["etag"]}
    ).status_code == 304


def test_repeated_if_none_match_lines_are_one_list() -> None:
    client = _client({"html": SHELL_V1})
    tag = client.get("/").headers["etag"]

    response = client.get("/", headers=[("If-None-Match", '"x"'), ("If-None-Match", tag)])

    assert response.status_code == 304


# ------------------------------------------------- composes with the gzip layer


def test_it_composes_with_the_gzip_middleware() -> None:
    client = _client({"html": SHELL_V1}, gzip=True)
    gzip_headers = {"Accept-Encoding": "gzip"}

    first = client.get("/", headers=gzip_headers)

    # The body is large enough to compress; the tag is still the one we set.
    assert first.headers["content-encoding"] == "gzip"
    assert first.headers["etag"] == etag_for(SHELL_V1)
    assert first.text == SHELL_V1

    revalidated = client.get(
        "/", headers={**gzip_headers, "If-None-Match": first.headers["etag"]}
    )

    assert revalidated.status_code == 304
    assert revalidated.content == b""
    assert "content-encoding" not in revalidated.headers
    assert revalidated.headers["etag"] == first.headers["etag"]
    assert revalidated.headers["cache-control"] == SHELL_CACHE_CONTROL
