# `site-theme` — the light/dark switch

A dark theme for a web page, chosen the way a visitor expects: the **system setting** decides until they press the switch, and **their choice is saved** (`localStorage`, key `theme`) and wins from then on. A saved choice is applied **before the first paint** by a one-line boot script, so a page never flashes the other theme. Without JavaScript the system setting still applies, because the colour scheme is pure CSS.

The component carries the switch, the scheme logic and the boot script. It carries **no dark colours**: those are the site's brand, set as tokens (below).

## Contract

- **State.** `data-theme="light"` or `"dark"` on `<html>` is the visitor's saved choice; absent means "follow the system". Nothing else stores a theme.
- **Scheme.** `site-theme.css` sets `color-scheme: light dark` on `:root`, narrowed to the chosen one by `data-theme`. A dark value is a `light-dark(<light>, <dark>)` token, which follows that scheme; no media query or second stylesheet per colour.
- **Switch.** One `button.theme-toggle` with `aria-pressed` (true while dark) and an `aria-label` that names the dark theme (a label that changes with the state is read twice). 44 px square, a moon in light and a sun in dark.
- **No flash.** `theme-boot.js` is a plain blocking `<script>` in `<head>` before the stylesheets. `site-theme.js` is a deferred module and only reads state at load; it writes `data-theme` on a press alone.
- **Storage blocked** (private mode, site data off): the press still switches the page, for that page only.
- **Floors hold in both themes.** Every contrast floor of `design.web.md` applies to the dark values, as to the light ones.

## What a site sets

Its dark values, in its own stylesheet (loaded last), as `light-dark()` tokens:

```css
:root {
  --paper: light-dark(#fff, #141414);
  --ink: light-dark(#111, #ececec);
  --ink-2: light-dark(#595959, #a3a3a3);
  --line: light-dark(#e3e3e3, #333);
  --line-strong: light-dark(#8c8c8c, #7a7a7a);
  --footer-band: light-dark(#595959, #2e2e2e);
  --ink-hover: light-dark(#333, #c8c8c8);
}
```

`--band-ink`, `--band-label` and `--band-rule` stay light in both themes: the footer band is dark either way. The `--pen-*` tokens are data-URI drawings with their colour baked in, so a site that wants the pen readable on dark points them at dark versions under `[data-theme="dark"]` and the same selector inside `@media (prefers-color-scheme: dark)` with `:root:not([data-theme="light"])`.

## Markup

```html
<head>
<script src="/_vendored/site-theme/theme-boot.js"></script>
<link rel="stylesheet" href="/_vendored/site-theme/site-theme.css">
…
</head>
…
<div class="site-header-end">
<nav class="site-nav" id="site-nav" aria-label="Main">…</nav>
<button class="theme-toggle" type="button" aria-pressed="false" aria-label="Dark theme"><svg class="icon moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg><svg class="icon sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/></svg></button>
<button class="menu-toggle" …>…</button>
</div>
<script type="module" src="/_vendored/site-theme/site-theme.js"></script>
```

Instead of the `theme-boot.js` request, paste its one code line inline as `<script>…</script>`; a test holds the two equal. Load `site-theme.css` after `site-tokens.css` and before the site's own stylesheet. Needs [`site-tokens`](../site-tokens/) (`--s2`, `--radius`, `--line`) and [`site-header`](../site-header/) (`.icon`, the header it sits in).

The icons are static [Lucide](https://lucide.dev) SVGs (ISC licence, [`LICENSE-lucide.txt`](LICENSE-lucide.txt)); they use `currentColor`, so they follow the text colour in both themes.

## Files

| File | Role |
| --- | --- |
| `theme-boot.js` | The blocking boot line: applies a saved choice before the first paint |
| `site-theme.js` | The switch (an ES module; the page works without it) |
| `site-theme.css` | The colour scheme, the icon swap, the switch and the header's right end |
| `LICENSE-lucide.txt` | The icons' licence |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-theme/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-theme`, never by hand. Do not edit the files per site: the dark brand is token values in the site's own stylesheet. Load order and the whole set: [`../README.md`](../README.md).
