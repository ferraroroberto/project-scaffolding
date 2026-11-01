# Site migration: moving a site off a hosted builder

A kit for the one-off job of moving a public site from a hosted builder (Squarespace, Wix, Webflow and the like) to a fleet **built static site** without losing what search engines and visitors rely on. It is separate from the web-page design standard and from the vendored site components (`docs/components.md`): the components are how every fleet site looks and is checked, and this kit runs once per site, until cutover, and is then retired.

The reference implementation is the fleet's first web page, the `robertoferraro` repo (its `scripts/`): `crawl.py`, `inventory.py`, `pagefacts.py`, `compare.py`, `render_checks.py`, `compare_report.py` and `compare_accepted.json`. They are not vendored: each names the old builder's hosts and the live site's quirks, so the next migration copies them as a starting point and adapts them.

## What must not regress

Per URL, the facts a search engine reads: the status, title, meta description, canonical URL, Open Graph and Twitter tags, the h1 and the heading outline, the body text, alt text, internal links, embeds, and the redirects for every moved URL. The new site may look different; these may not silently change.

## The tools

| Tool | What it does |
| --- | --- |
| `crawl.py` | A polite crawl of the live site into a scratch folder outside the repo: the sitemap plus every internal link, saved as raw HTML with a status ledger, and every asset the builder hosts, at original resolution. A real browser user agent, one request per second, retries with backoff; a rerun skips what is on disk. |
| `inventory.py` | Writes the site's `inventory.md` (in its docs) from a crawl: every live URL with its SEO facts and embeds. The checklist of what the new site must carry. |
| `pagefacts.py` | Extracts the SEO and content facts of one HTML page. The inventory and the compare both read pages through it, so a difference in the report is a difference in the pages, never in how they were measured. |
| `compare.py` | The local preview against the live site, URL by URL. A content pass on the raw HTML (the facts above, plus whether every image loads) and a rendered pass per viewport through `render_checks.py`. Writes the site's `compare-report.md` (in its docs); exit 0 when no open difference remains. Start the preview server (`site_serve.py`) first. |
| `render_checks.py` | The rendered half, in Playwright Chromium at desktop and phone width: sideways scrolling, every live image still shown, broken images, the fonts of the main text roles, embed widths, the navigation, and on a phone the links a tap on the menu reaches. Heights and image boxes are not compared, because the new site has its own design. |
| `compare_report.py` | Splits the findings per URL and pass into open and accepted. |
| `compare_accepted.json` | The differences accepted on purpose, each with `path` (a glob), `viewport`, `check`, `contains` and a `reason`. An accepted difference is reported with its reason; anything else is open. |

## How it runs

1. Crawl the live site once and write the inventory; copy the owner's content and images from the crawl into `content/`.
2. Build the site, and add a `_redirects` line for every URL that moves.
3. Before each merge, run the compare against the live site and take it to zero open differences: fix the page, or accept the difference with its reason.
4. The day before cutover, run the compare once more, and run `site_check.py` with the old builder's CDN hosts as `--forbid-host`, so nothing still loads from a host that disappears with the plan.
5. After cutover, retire the kit: the compare has nothing left to compare against.

The compare is not part of the gate: it needs the live site, and the gate runs offline.

## Gotchas

- **Accepted differences match a substring near the start.** The compare truncates a finding's message at about 720 characters, so a `contains` must match text that appears early, on the live side of the message.
- **Raw HTML and rendered passes disagree for script-rendered content.** A builder that renders forms or galleries with a script has no field labels or images in the page source; accept those with the reason, never by loosening the check.
- **A link that 404s on the live site too** is kept so the links match, and passed to `site_check.py` as `--allow-missing`, with the fix tracked in the site's own issues.
- **Line endings.** The build writes LF and the gate compares bytes, so `content/` and `site/` are LF through `.gitattributes`; edit them with tools that keep the endings.
