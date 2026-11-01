"""How a static host maps a URL path to a file under the built site folder.

One place owns the Cloudflare Pages URL rules, so the preview server (`site_serve.py`) and
the offline site check (`site_check.py`) agree on what a path serves: `/` is `index.html`,
an extensionless path is `<path>.html`, and exact-match `_redirects` lines redirect.

Vendor-verbatim (manifest key `site_routes`), stdlib-only. `site_serve.py` and
`site_check.py` import it as `scripts.site_routes`: vendor all three into the repo's `scripts/`.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote


def load_redirects(site_dir: Path) -> dict[str, tuple[str, int]]:
    """Exact-match `_redirects` rules: source path -> (destination, status)."""
    rules: dict[str, tuple[str, int]] = {}
    path = site_dir / "_redirects"
    if not path.exists():
        return rules
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2 and "*" not in fields[0] and ":" not in fields[0]:
            rules[fields[0].rstrip("/") or "/"] = (fields[1], int(fields[2]) if len(fields) > 2 else 302)
    return rules


def resolve_file(site_dir: Path, url_path: str) -> Path | None:
    """The file under `site_dir` that serves `url_path`, or None for a miss."""
    rel = unquote(url_path).lstrip("/")
    candidates = [site_dir / "index.html"] if not rel else [site_dir / rel, site_dir / f"{rel.rstrip('/')}.html"]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file() and resolved.is_relative_to(site_dir.resolve()):
            return resolved
    return None
