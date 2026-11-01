# `site-pen` — the pen

The brand accent drawn by hand, as strokes behind words that repeat on every line they wrap to: `.hl-marker` behind one or two title words, `.hl-underline` under one phrase of running text, `.hl-strike` through a word. A highlighted link is shown by its stroke alone, and hovering thickens it. The marker goes only on title words and the current nav item. `.hl-circle` is retired and draws the underline.

## Markup

```html
<h1 class="title">Draw <mark class="hl hl-marker">clearly</mark></h1>
<p>Text with <span class="hl hl-underline">one phrase</span> underlined.</p>
```

The strokes are the `--pen-*` tokens in [`site-tokens`](../site-tokens/), where a site recolours them.

## Files

| File | Role |
| --- | --- |
| `site-pen.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-pen/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-pen`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
