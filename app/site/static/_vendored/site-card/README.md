# `site-card` — the card

A framed square picture with the words underneath on the paper, and no box around the whole card. The card's first text link (or its button) is stretched over the whole card, so the card is one target; hovering darkens the frame. Photos, portraits and covers fill the square; drawings (`.drawing`) sit whole inside it. A card's button reads as its title, with an arrow. `.cards` is a three-column grid from 768 px; on a phone a list of cards becomes rows, the thumbnail beside the words.

- Card copy of one length (35 to 45 words) makes a row of cards end level.

## Markup

```html
<div class="cards">
<article class="card">
<a href="/coaching" aria-hidden="true" tabindex="-1"><img class="drawing" src="…" alt=""></a>
<p class="btns"><a class="btn" href="/coaching">Coaching</a></p>
</article>
</div>
```

Needs [`site-tokens`](../site-tokens/), [`site-image`](../site-image/) and [`site-button`](../site-button/).

## Files

| File | Role |
| --- | --- |
| `site-card.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-card/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-card`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
