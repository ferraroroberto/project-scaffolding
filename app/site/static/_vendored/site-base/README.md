# `site-base` — reset, type by role, links and focus

The element layer under every other component: `box-sizing`, the body font and colour, images as blocks, heading weights, the type scale applied by role (`.title`, `.title.long`, `.lead`, `.small`, card text), link underlines that thicken on hover, one `:focus-visible` ring, `blockquote`, `hr`, and the reduced-motion switch that turns every transition off.

- **One left edge.** `.center` and `.right` resolve to `start`: centred section text was the most-flagged inconsistency of the old site.
- Sizes follow the role, not the element: a page's first heading gets `.title` from the build, whatever its level, and a long one (`.title.long`) is set a size smaller.

Needs [`site-tokens`](../site-tokens/).

## Files

| File | Role |
| --- | --- |
| `site-base.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-base/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-base`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
