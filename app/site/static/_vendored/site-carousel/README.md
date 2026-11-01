# `site-carousel` — the whole-card carousel

A row of whole cards that scrolls sideways with scroll snap: three from 1024 px, two from 640 px, and on a phone 82% of the width so the next card's edge shows. The columns come from `grid-auto-columns: calc((100% - (n - 1) * gap) / n)`, never from fixed card widths. `site-carousel.js` wires the arrows the build places after each track: centred under the row, hidden when nothing scrolls, disabled at either end, one card per click, instant under reduced motion. No carousels of single images.

## Markup

```html
<div class="carousel" data-carousel>
<article class="card">…</article>
<article class="card">…</article>
</div>
<div class="swipe-nav" hidden>
<button type="button" aria-label="Previous"><svg class="icon">…chevron-left…</svg></button>
<button type="button" aria-label="Next"><svg class="icon">…chevron-right…</svg></button>
</div>
<script type="module" src="/_vendored/site-carousel/site-carousel.js"></script>
```

The selectors also cover the reference site's `.gallery.slides` and `.gallery.reel`. Needs [`site-tokens`](../site-tokens/) and [`site-card`](../site-card/).

## Files

| File | Role |
| --- | --- |
| `site-carousel.css` | Styles |
| `site-carousel.js` | Behaviour (an ES module; the page works without it) |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-carousel/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-carousel`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
