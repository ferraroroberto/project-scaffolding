# The `[components]` catalog

`.fleet.toml`'s `[components]` table is the canonical `<manifest key> → <src path>` map of every vendor-verbatim component this scaffold publishes, read by `scripts/vendored_catalog.py`. Only this repo carries it — an adopter declares what it copied in its own `[vendored]` table instead; this one declares what the scaffold publishes, and only the scaffold publishes.

## Why it exists

`/propagate-vendored <component>` builds its adopter list from adopters' `[vendored]` entries. A repo that carries a component without declaring it is invisible to that wave: the fan-out re-vendors the declared repos, reports success, and leaves the undeclared carrier stale.

It is load-bearing in two more places:

- `fleet-config`'s `vendored_drift.py` hashes every fleet repo's copy of a catalogued path to name repos carrying an undeclared component.
- `scripts/verify-before-ship.ps1` derives its `mypy --strict` gate list from the same declaration, rather than keeping a second hand-maintained list, so a new Python component is type-gated the day it lands.

## Keeping it current

Add a component to the table in the same PR that adds it to the tree. `tests/test_vendored_catalog.py` is the anti-drift guard that fails otherwise.

## The web-page (static site) set

A fleet **web page** is a public, static, content-first site served as a folder from a CDN. Its components are a separate set from the web-app ones, because the app set is app-shaped (a floating tab pill, light and dark, data and controls) and a site is not (a top header with a phone menu, the owner's brand, text and images, light only). They were extracted from the fleet's first web page without changing its look: every CSS and JS rule is a verbatim copy, and the Python keeps its behaviour with the site-specific constants turned into arguments.

| Manifest key | Source | What |
| --- | --- | --- |
| `site-tokens` | `app/site/static/_vendored/site-tokens/` | The token contract with the reference brand values; a site overrides only its brand tokens. |
| `site-base` | `app/site/static/_vendored/site-base/` | Reset, type by role, links, focus, one left edge, reduced motion. |
| `site-header` | `app/site/static/_vendored/site-header/` | Header, text nav, full-width phone menu (CSS + JS). |
| `site-section` | `app/site/static/_vendored/site-section/` | Bands, the drawn rule, rows with media columns at their role's width, the phone order. |
| `site-image` | `app/site/static/_vendored/site-image/` | One frame for every content image; drawings, photos and cut-outs. |
| `site-video` | `app/site/static/_vendored/site-video/` | A thumbnail until tapped (CSS + JS). |
| `site-button` | `app/site/static/_vendored/site-button/` | The button. |
| `site-card` | `app/site/static/_vendored/site-card/` | The card: framed square picture, words underneath, one stretched link. |
| `site-testimonial` | `app/site/static/_vendored/site-testimonial/` | The framed quote tile. |
| `site-carousel` | `app/site/static/_vendored/site-carousel/` | Whole-card carousel with centred arrows (CSS + JS). |
| `site-product` | `app/site/static/_vendored/site-product/` | Product grid and product page. |
| `site-pen` | `app/site/static/_vendored/site-pen/` | The drawn marker, underline and strike. |
| `site-footer` | `app/site/static/_vendored/site-footer/` | The dark footer band. |
| `site_images` | `scripts/site_images.py` | Build-time WebP variants per role, a 1200 px social JPEG, cut-out and drawing detection, the grey-paper swap. Needs Pillow. |
| `site_routes` | `scripts/site_routes.py` | The static host's URL rules (`/about` from `about.html`, exact-match `_redirects`). |
| `site_serve` | `scripts/site_serve.py` | Preview server with those rules; `--host` for a phone over the tailnet. Needs `site_routes`. |
| `site_check` | `scripts/site_check.py` | Offline gate check: every sitemap URL resolves, no file names a `--forbid-host`, no broken local reference. Exit 3 is not confirmed. Needs `site_routes`. |

The CSS components load in the order of the table, then the site's own stylesheet last; `app/site/static/_vendored/README.md` has the load order, the brand split and what stays the site's own. `site_serve` and `site_check` import `site_routes` as `scripts.site_routes`, so the three go into the site's `scripts/` together. A built site's layout is the `static-site` shape in `docs/repo-layout.md`, and its `[e2e]` table is in `docs/e2e-routing.md`. Moving a site off a hosted builder uses a separate kit: `docs/site-migration.md`.
