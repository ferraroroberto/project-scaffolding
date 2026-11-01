# `site-footer` — the footer

The dark band that ends every page: white text at 7:1 or better on `--footer-band`, label heads at 4.5:1 or better, and 44 px link rows. On a phone the first column spans the width and the two link columns sit side by side, their links starting level; from 768 px the row is `2fr 1fr 1fr`.

## Markup

```html
<footer class="site-footer">
<section class="band">
<div class="wrap">
<div class="row">
<div class="col"><div class="b text"><h3>Let us talk</h3><p>One line on how to reach you.</p></div></div>
<div class="col"><div class="b text"><p><strong>About</strong></p><p><a href="/about">About</a><br><a href="/contact">Contact</a></p></div></div>
<div class="col"><div class="b text"><p><strong>Work</strong></p><p><a href="/services">Services</a></p></div></div>
</div>
</div>
</section>
</footer>
```

Needs [`site-tokens`](../site-tokens/) and [`site-section`](../site-section/).

## Files

| File | Role |
| --- | --- |
| `site-footer.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-footer/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-footer`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
