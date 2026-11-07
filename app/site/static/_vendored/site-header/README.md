# `site-header` — header, text nav and phone menu

The brand on the left, the text nav on the right; under the nav breakpoint (1024 px unless the site sets one) a 44 px menu button opens a full-width panel under the header. The current page's nav item carries the pen marker. `site-header.js` adds the hairline once the page scrolls and the menu's open, close, Escape and link-tap behaviour; the page works without it.

- **The brand never shrinks.** `.logo` is `flex: none` and the image keeps `width: auto` at its set height, so a long nav cannot squeeze the wordmark sideways.
- **The nav breakpoint is a token.** A site with a long nav sets `--nav-breakpoint` on `:root` in its own stylesheet (for example `1200px`, a px length). `site-header.js` reads it, marks the header `data-nav="menu"` below it and `data-nav="inline"` from it, and closes an open menu when the nav goes inline. A media query cannot read a custom property, which is why the script applies it. The stylesheet's own 1024 px query is the floor, so a value below 1024 px or one that is not in px is ignored, and without the script the breakpoint is 1024 px. The script runs deferred, so a site above 1024 px can show the text nav for a moment between 1024 px and its breakpoint on first paint.
- **The logo height is the site's.** The component sets 32 px (40 px from 1024 px); a site whose nav and wordmark need a different size beside each other sets it in its own stylesheet.

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
