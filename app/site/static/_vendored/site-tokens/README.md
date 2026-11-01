# `site-tokens` — the token contract

Every custom property the other site components read, on `:root`: the 4 px space scale (`--s1`..`--s9`, `--gutter`, `--gap`, `--section`), the type scale by role (`--fs-title`, `--fs-h2`, `--fs-h3`, `--fs-lead`, `--fs-body`, `--fs-card`, `--fs-small`, `--fs-label`), one radius and one hairline frame (`--radius`, `--frame`), `--control`, `--header`, the layout width (`--content`, `--measure`), the image roles (`--img-feature`, `--img-tile`, `--img-thumb`, re-set at 768 and 1024 px) and the pen (`--pen-rule`, `--pen-marker`, `--pen-underline`, `--pen-quote`, `--pen-strike`).

## Contract and brand

The names and roles are the contract; some values are the brand. The values shipped here are the reference site's, so a site that sets nothing looks like it. A site sets its brand in its own stylesheet, loaded **after** this file, by redefining only these on `:root`:

| Brand token | Role |
| --- | --- |
| `--paper`, `--ink`, `--ink-2`, `--line`, `--line-strong` | paper, text, secondary text, hairline, field border |
| `--accent` | the pen colour only: never text, border, button or fill |
| `--footer-band` | the footer band; white on it at 7:1 or better |
| `--font` | the one sans family (the site ships its own `@font-face` rules) |
| `--pen-*` | the drawn SVGs, whose colours are baked into each data URI |

Everything else is contract: change it here, for every site.

## Image roles

One size per role whatever the column: feature `min(520px, half the row)` from 768 px (the whole width on a phone), tile half then a third of the row, thumb 96 then 160 px. A feature is a `min()` of the role and half the row, not a `minmax(0, 520px)` grid track: a fixed max track grows to its max before an `fr` track gets anything, which left a 152 px text column at 800 px. `.wrap` (in [`site-section`](../site-section/)) is the size container, so `100cqi` is the content width.

## Files

| File | Role |
| --- | --- |
| `site-tokens.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-tokens/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-tokens`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
