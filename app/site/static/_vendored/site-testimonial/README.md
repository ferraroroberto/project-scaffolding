# `site-testimonial` — the testimonial

A testimonial is a card whose quote is the framed tile, with the drawn quote mark (`--pen-quote`); the person's name sits below as a label. In a [`site-carousel`](../site-carousel/) the testimonials show as a 3 x 2 grid on a desktop, with nothing to scroll.

## Markup

```html
<article class="card">
<h2 class="quote">What they said, in their words.</h2>
<p>Name, role</p>
</article>
```

Needs [`site-tokens`](../site-tokens/) and [`site-card`](../site-card/).

## Files

| File | Role |
| --- | --- |
| `site-testimonial.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-testimonial/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-testimonial`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
