# `site-product` — the product grid and page

`.products` is a grid of product cards (two columns, four from 768 px). The product page puts the picture on the left at the feature size and the text on the right at the measure: title, the price at the lead size, Buy directly under it, then the description. From 768 px the picture is sticky and centred in the space under the header, so no tall blank stretch opens beside a long description; it starts at most 160 px down.

## Markup

```html
<div class="product">
<div class="product-media"><img class="drawing" src="…" alt=""></div>
<div class="product-info">
<h1 class="title">Product name</h1>
<p class="price">€100.00</p>
<p class="btns"><a class="btn" href="…">Buy</a></p>
<p>Description.</p>
</div>
</div>
```

Needs [`site-tokens`](../site-tokens/), [`site-image`](../site-image/) and [`site-button`](../site-button/).

## Files

| File | Role |
| --- | --- |
| `site-product.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-product/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-product`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
