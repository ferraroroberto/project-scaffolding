"""Offline gate check of a built static site: routes, foreign hosts, broken local references.

1. Every <loc> in `site/sitemap.xml` resolves to a file at the same path.
2. No file under `site/` names a host passed with `--forbid-host` (for a migrated site, the
   old builder's CDN hosts, which vanish with its plan).
3. Every local href, src, srcset and CSS url() resolves to a file, or to a `_redirects` rule.
   A link to the site's own host counts as local; the own hosts are the sitemap's <loc>
   hosts, with and without `www.`. `--allow-missing PATH` keeps a link known to be broken
   on purpose (one that 404s on the live site too) out of the findings.

Exit 0 clean, 1 on findings, 3 when the check cannot run (no site/ or no sitemap).

    .venv/Scripts/python.exe scripts/site_check.py [--site-dir site] [--forbid-host HOST ...] [--allow-missing PATH ...]

Vendor-verbatim (manifest key `site_check`), stdlib-only; needs `site_routes.py` beside it.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

# The URL rules live in the sibling `scripts/site_routes.py`; the repo root on the path finds it
# whether this runs as a script (also under `python -P`) or is imported as `scripts.<name>`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.site_routes import load_redirects, resolve_file  # noqa: E402

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
TEXT_SUFFIXES = frozenset({".html", ".css", ".js", ".xml", ".txt", ".json", ".webmanifest", ""})
CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "about:")
URL_ATTRS = ("href", "src", "poster", "data-src", "xlink:href")
SRCSET_ATTRS = ("srcset", "imagesrcset")
EXIT_CLEAN, EXIT_FINDINGS, EXIT_NOT_CONFIRMED = 0, 1, 3
log = logging.getLogger("check")


class _RefParser(HTMLParser):
    """Collects every URL a page loads or links while it parses."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._in_style = tag == "style"
        for name, value in attrs:
            if value is None or not value.strip():
                continue
            if name in URL_ATTRS:
                self.refs.append(value.strip())
            elif name in SRCSET_ATTRS:
                self.refs += [part.strip().split()[0] for part in value.split(",") if part.strip()]
            elif name == "style":
                self.refs += CSS_URL_RE.findall(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.refs += CSS_URL_RE.findall(data)


def html_refs(html: str) -> list[str]:
    """Every URL a page loads or links: href, src, srcset, poster and inline-style url()."""
    parser = _RefParser()
    parser.feed(html)
    parser.close()
    return parser.refs


def page_url_path(site_dir: Path, file: Path) -> str:
    """The URL path a file under `site_dir` is served at (about.html -> /about)."""
    rel = file.relative_to(site_dir).as_posix()
    if rel == "index.html":
        return "/"
    return "/" + (rel[:-5] if rel.endswith(".html") else rel)


def sitemap_locs(site_dir: Path) -> list[str]:
    """The <loc> URLs of `site_dir/sitemap.xml`, in file order."""
    return LOC_RE.findall((site_dir / "sitemap.xml").read_text(encoding="utf-8"))


def own_hosts(locs: list[str]) -> frozenset[str]:
    """The site's own hosts: every sitemap host, with and without `www.`."""
    hosts: set[str] = set()
    for loc in locs:
        host = urlsplit(loc).netloc.lower()
        if host:
            bare = host.removeprefix("www.")
            hosts |= {bare, f"www.{bare}"}
    return frozenset(hosts)


def local_target(base_path: str, ref: str, hosts: frozenset[str], allow_missing: frozenset[str]) -> str | None:
    """The site path `ref` points at, or None when it leaves the site or needs no file."""
    if ref.startswith(SKIP_SCHEMES) or unquote(ref).startswith("#"):
        return None
    url = urljoin(base_path, ref)
    parts = urlsplit(url)
    if (parts.netloc and parts.netloc.lower() not in hosts) or parts.path in allow_missing:
        return None
    return parts.path or "/"


def check_sitemap(site_dir: Path, locs: list[str]) -> list[str]:
    """Sitemap paths with no file behind them."""
    paths = [urlsplit(loc).path or "/" for loc in locs]
    return [f"sitemap path {p} has no file" for p in paths if resolve_file(site_dir, p) is None]


def check_hosts(site_dir: Path, forbidden: frozenset[str]) -> list[str]:
    """Files that still name a forbidden host."""
    findings: list[str] = []
    if not forbidden:
        return findings
    for file in sorted(site_dir.rglob("*")):
        if not file.is_file() or file.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        hits = sorted(host for host in forbidden if host in text)
        if hits:
            findings.append(f"{file.relative_to(site_dir).as_posix()} names {', '.join(hits)}")
    return findings


def check_references(site_dir: Path, hosts: frozenset[str], allow_missing: frozenset[str]) -> list[str]:
    """Local references that resolve to no file and no redirect rule."""
    redirects = load_redirects(site_dir)
    findings: list[str] = []
    sources = [(f, html_refs(f.read_text(encoding="utf-8"))) for f in sorted(site_dir.rglob("*.html"))]
    sources += [(f, CSS_URL_RE.findall(f.read_text(encoding="utf-8"))) for f in sorted(site_dir.rglob("*.css"))]
    for file, refs in sources:
        base = page_url_path(site_dir, file)
        for ref in refs:
            target = local_target(base, ref, hosts, allow_missing)
            if target is None or (target.rstrip("/") or "/") in redirects:
                continue
            if resolve_file(site_dir, target) is None:
                findings.append(f"{file.relative_to(site_dir).as_posix()}: {ref} -> {target} missing")
    return findings


def run(site_dir: Path, forbidden: frozenset[str], allow_missing: frozenset[str]) -> int:
    """Run the three checks over `site_dir` and return the gate exit code."""
    if not (site_dir / "sitemap.xml").is_file():
        log.error("❌ NOT CONFIRMED: %s/sitemap.xml is missing", site_dir)
        return EXIT_NOT_CONFIRMED
    locs = sitemap_locs(site_dir)
    hosts = own_hosts(locs)
    findings = check_sitemap(site_dir, locs) + check_hosts(site_dir, forbidden) + check_references(site_dir, hosts, allow_missing)
    for finding in findings:
        log.error("❌ %s", finding)
    if findings:
        log.error("❌ site check: %d finding(s)", len(findings))
        return EXIT_FINDINGS
    log.info("✅ site check: sitemap routes, hosts and local references clean")
    return EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run the check."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--site-dir", type=Path, default=SITE_DIR, help="the built site folder (default: site/ at the repo root)")
    parser.add_argument("--forbid-host", action="append", default=[], metavar="HOST", help="a host no built file may name; repeatable")
    parser.add_argument("--allow-missing", action="append", default=[], metavar="PATH", help="a local path known to be broken on purpose; repeatable")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return run(args.site_dir, frozenset(h.lower() for h in args.forbid_host), frozenset(args.allow_missing))


if __name__ == "__main__":
    sys.exit(main())
