# `site-header` — header, text nav and phone menu

The brand on the left, the text nav on the right; under 1024 px a 44 px menu button opens a full-width panel under the header. The current page's nav item carries the pen marker. `site-header.js` adds the hairline once the page scrolls and the menu's open, close, Escape and link-tap behaviour; the page works without it.

- **Never put `backdrop-filter`, `filter` or `transform` on `.site-header`.** Any of them makes the header the containing block of the `position: fixed` menu panel, which then sizes itself to the 64 px header and is invisible. Test a menu by hit-testing each link's centre with `elementFromPoint`, not by its bounding box.

## Markup

```html
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
<div class="site-header-inner">
<a class="logo" href="/"><img src="/images/logo.png" alt="Site name"></a>
<button class="menu-toggle" type="button" aria-controls="site-nav" aria-expanded="false" aria-label="Menu"><svg class="icon">…menu…</svg><svg class="icon">…x…</svg></button>
<nav class="site-nav" id="site-nav" aria-label="Main">
<ul>
<li><a href="/" aria-current="page"><span>Home</span></a></li>
<li><a href="/about"><span>About</span></a></li>
</ul>
</nav>
</div>
</header>
<script type="module" src="/_vendored/site-header/site-header.js"></script>
```

Needs [`site-tokens`](../site-tokens/) (`--header`, `--pen-marker`).

## Files

| File | Role |
| --- | --- |
| `site-header.css` | Styles |
| `site-header.js` | Behaviour (an ES module; the page works without it) |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-header/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-header`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
