# `_vendored/` — fleet web-page component library

Byte-copyable components for a fleet **web page**: a public, static, content-first site served as a folder from a CDN, read once by a stranger, mostly on a phone. They are the web-page counterpart of the web-app set in `app/webapp/static/_vendored/`, which is app-shaped (a floating tab pill, light and dark, data and controls) and does not fit a site.

The rules were first built and proven on the fleet's first web page and extracted from it without changing the look: every CSS and JS rule here is copied from that site's one stylesheet and one script, in their original order within each component. `fleet-config` owns the spec (`design.web.md`); this folder owns the implementation.

## Components

| Folder | What |
| --- | --- |
| [`site-tokens/`](site-tokens/) | The token contract: 4 px space scale, type scale by role, one radius and one hairline, `--content`, `--measure`, the image roles and the pen SVGs. Ships the reference brand values; a site overrides only its brand tokens. |
| [`site-base/`](site-base/) | The reset, type by role, links, one focus ring, one left edge, reduced motion. |
| [`site-header/`](site-header/) | Brand left, text nav right; a full-width phone menu under 1024 px. Never a `backdrop-filter` on the header. |
| [`site-section/`](site-section/) | White bands separated by the drawn rule; the row layout with one left edge and media columns at their role's width; the phone order. |
| [`site-image/`](site-image/) | One frame and radius for every content image; drawings `contain`, photos `cover`, cut-outs keep their shape. |
| [`site-video/`](site-video/) | A thumbnail until tapped; the nocookie YouTube player loads only then. |
| [`site-button/`](site-button/) | One control height, one radius; secondary and disabled. |
| [`site-card/`](site-card/) | A framed square picture with the words underneath, no box, one stretched link; rows on a phone. |
| [`site-testimonial/`](site-testimonial/) | A framed quote tile with the drawn quote mark; 3 x 2 on a desktop. |
| [`site-carousel/`](site-carousel/) | Whole cards only (3, 2, then 82% with the next edge); arrows centred under the row, one card per click. |
| [`site-product/`](site-product/) | The product grid, and the product page with its sticky, centred picture and Buy under the price. |
| [`site-pen/`](site-pen/) | The hand-drawn marker, underline and strike behind words. |
| [`site-footer/`](site-footer/) | The dark band: 7:1 text, 44 px link rows, two link columns on a phone. |

The build-side Python is in `scripts/` (manifest keys `site_images`, `site_routes`, `site_serve`, `site_check`); [`docs/components.md`](../../../../docs/components.md) lists the whole set.

## Load order

Stylesheets in this order, then the site's own stylesheet last, so its brand tokens and its own components win:

```html
<link rel="stylesheet" href="/_vendored/site-tokens/site-tokens.css">
<link rel="stylesheet" href="/_vendored/site-base/site-base.css">
<link rel="stylesheet" href="/_vendored/site-header/site-header.css">
<link rel="stylesheet" href="/_vendored/site-section/site-section.css">
<link rel="stylesheet" href="/_vendored/site-image/site-image.css">
<link rel="stylesheet" href="/_vendored/site-video/site-video.css">
<link rel="stylesheet" href="/_vendored/site-button/site-button.css">
<link rel="stylesheet" href="/_vendored/site-card/site-card.css">
<link rel="stylesheet" href="/_vendored/site-testimonial/site-testimonial.css">
<link rel="stylesheet" href="/_vendored/site-carousel/site-carousel.css">
<link rel="stylesheet" href="/_vendored/site-product/site-product.css">
<link rel="stylesheet" href="/_vendored/site-pen/site-pen.css">
<link rel="stylesheet" href="/_vendored/site-footer/site-footer.css">
<link rel="stylesheet" href="/css/site.css">
```

A site with a build may instead concatenate them, in the same order, into its one stylesheet, which saves a dozen requests on a cold phone load; the copies under `_vendored/` stay byte-identical either way. The scripts are ES modules (`<script type="module">`), each independent.

## What stays the site's own

The brand and the components only one site has: its `@font-face` rules and font files, its brand token values, and anything not listed above (the reference site keeps its embeds, accordion, social links, galleries and forms in its own stylesheet). A component a second site needs graduates here, normalised, in its own PR.
