# `site-button` — the button

One control height (`--control`), one radius, ink fill with paper text; `.btn.secondary` is paper with an ink border; a disabled button is dashed and muted. Buttons sit in a `p.btns`. [`site-card`](../site-card/) restyles a card's button as its title with an arrow; [`site-product`](../site-product/) puts Buy directly under the price.

## Markup

```html
<p class="btns"><a class="btn" href="/contact">Get in touch</a></p>
```

Needs [`site-tokens`](../site-tokens/).

## Files

| File | Role |
| --- | --- |
| `site-button.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-button/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-button`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
