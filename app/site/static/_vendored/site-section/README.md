# `site-section` — bands, the drawn rule and the row layout

A page is a stack of white `section.band`s, separated by space and one hand-drawn ink rule (`--pen-rule`), never by grey bands. Inside, `.wrap` is the centred content column and the size container. On a phone every band is one evenly spaced column; from 768 px each `.row` lays its `.col`s side by side from one left edge, sharing the width equally, and a column marked `media` takes its image role's width beside the text (`feature`, `thumb`, or tile by default).

- **The phone order is a rule, not a per-page fix:** title, text, picture, then button or form. A block whose phone order differs from its reading order sets `--m` (its `order`) inline.
- A guest's portrait (`.col.thumb`) beside their entry stays a row on a phone, with the name set as a card title.

## Markup

```html
<main id="main">
<section class="band">
<div class="wrap">
<div class="row">
<div class="col"><div class="b text"><h2>Heading</h2><p>Text at the measure.</p></div></div>
<div class="col media feature"><figure class="b img"><img src="…" alt="…"></figure></div>
</div>
</div>
</section>
</main>
```

The build marks `media` and its role. Needs [`site-tokens`](../site-tokens/) and [`site-image`](../site-image/).

## Files

| File | Role |
| --- | --- |
| `site-section.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-section/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-section`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
