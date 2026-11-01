"""The offline site check and the URL rules it shares with the preview server.

Each test builds a tiny `site/` in a temp folder and runs the check over it, so the three
findings (sitemap route, forbidden host, broken local reference) and the not-confirmed exit
are pinned without a real site.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import site_check
from scripts.site_routes import load_redirects, resolve_file

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.example.org/</loc></url>
<url><loc>https://www.example.org/about</loc></url>
</urlset>
"""


def build(root: Path, files: dict[str, str]) -> Path:
    site = root / "site"
    for rel, text in {"sitemap.xml": SITEMAP, "index.html": "<p>home</p>", "about.html": "<p>about</p>", **files}.items():
        path = site / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return site


def run(site: Path, forbid: tuple[str, ...] = (), allow: tuple[str, ...] = ()) -> int:
    return site_check.run(site, frozenset(forbid), frozenset(allow))


def test_a_clean_site_passes(tmp_path: Path) -> None:
    site = build(tmp_path, {
        "index.html": '<a href="/about">About</a><img src="/img/a.webp" srcset="/img/a.webp 480w, /img/b.webp 800w">'
                      '<a href="https://www.example.org/about">own host</a><a href="https://elsewhere.net/x">away</a>'
                      '<a href="mailto:a@example.org">mail</a><a href="#top">top</a>',
        "img/a.webp": "", "img/b.webp": "",
        "css/site.css": ".x { background: url(/img/a.webp); }",
    })
    assert run(site) == site_check.EXIT_CLEAN


def test_a_sitemap_url_with_no_file_is_a_finding(tmp_path: Path) -> None:
    site = build(tmp_path, {})
    (site / "about.html").unlink()
    assert site_check.check_sitemap(site, site_check.sitemap_locs(site)) == ["sitemap path /about has no file"]
    assert run(site) == site_check.EXIT_FINDINGS


def test_a_forbidden_host_is_a_finding_only_when_named(tmp_path: Path) -> None:
    site = build(tmp_path, {"index.html": '<img src="https://cdn.oldbuilder.com/x.png" alt="">'})
    assert run(site) == site_check.EXIT_CLEAN
    assert site_check.check_hosts(site, frozenset({"cdn.oldbuilder.com"})) == ["index.html names cdn.oldbuilder.com"]
    assert run(site, forbid=("cdn.oldbuilder.com",)) == site_check.EXIT_FINDINGS


@pytest.mark.parametrize("ref", [
    "/missing", "img/none.webp", "https://example.org/gone",  # the bare host is the site's own too
])
def test_a_broken_local_reference_is_a_finding(tmp_path: Path, ref: str) -> None:
    site = build(tmp_path, {"index.html": f'<a href="{ref}">x</a>'})
    assert run(site) == site_check.EXIT_FINDINGS


def test_inline_style_and_style_blocks_are_read(tmp_path: Path) -> None:
    refs = site_check.html_refs('<div style="background:url(\'/a.png\')"></div><style>.b{background:url(/b.png)}</style>'
                                '<p>url(/not-css.png)</p><link rel="preload" imagesrcset="/c.webp 1x, /d.webp 2x">')
    assert refs == ["/a.png", "/b.png", "/c.webp", "/d.webp"]


def test_a_redirect_rule_or_an_allowed_path_is_not_a_finding(tmp_path: Path) -> None:
    site = build(tmp_path, {"index.html": '<a href="/old">x</a><a href="/manifesto">y</a>', "_redirects": "/old /about 301\n"})
    assert run(site) == site_check.EXIT_FINDINGS
    assert run(site, allow=("/manifesto",)) == site_check.EXIT_CLEAN


def test_no_sitemap_is_not_confirmed_never_clean(tmp_path: Path) -> None:
    site = build(tmp_path, {})
    (site / "sitemap.xml").unlink()
    assert run(site) == site_check.EXIT_NOT_CONFIRMED


def test_main_reads_the_arguments(tmp_path: Path) -> None:
    site = build(tmp_path, {"index.html": '<img src="https://cdn.oldbuilder.com/x.png" alt="">'})
    assert site_check.main(["--site-dir", str(site)]) == site_check.EXIT_CLEAN
    assert site_check.main(["--site-dir", str(site), "--forbid-host", "CDN.oldbuilder.com"]) == site_check.EXIT_FINDINGS


def test_the_url_rules_match_the_static_host(tmp_path: Path) -> None:
    site = build(tmp_path, {"blog/post.html": "", "_redirects": "/a /b\n/c /d 301 # moved\n/e/* /f 301\n/g/:x /h\n"})
    assert resolve_file(site, "/") == (site / "index.html").resolve()
    assert resolve_file(site, "/about") == (site / "about.html").resolve()
    assert resolve_file(site, "/blog/post/") == (site / "blog/post.html").resolve()
    assert resolve_file(site, "/nope") is None
    assert resolve_file(site, "/../outside") is None
    assert load_redirects(site) == {"/a": ("/b", 302), "/c": ("/d", 301)}, "splats and placeholders are not exact-match"
