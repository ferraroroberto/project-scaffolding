# `site-image` — one frame for every content image

Every content image in `main` gets the hairline frame, the one radius and white paper behind it, and shows whole at its own proportions. A cut-out (`.cutout`, transparent corners) keeps its own shape with no frame; a drawing (`.drawing`) beside text sits whole in a square frame (`contain`), a photo fills it (`cover`). An image the author placed in a narrow column (`.img.narrow`) stays small on a phone. Portraits are square sources rounded by CSS, never baked circles.

The build adds the classes: `site_images.ImageSet.is_cutout` and `has_paper` decide `cutout` and `drawing` (manifest key `site_images`).

Needs [`site-tokens`](../site-tokens/).

## Files

| File | Role |
| --- | --- |
| `site-image.css` | Styles |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-image/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-image`, never by hand. Do not edit the files per site: the brand is token values in the site's own stylesheet (see [`site-tokens`](../site-tokens/)). Load order and the whole set: [`../README.md`](../README.md).
