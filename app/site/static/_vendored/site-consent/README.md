# `site-consent` — the consent bar

A non-modal bar fixed to the bottom edge. **Accept** and **Reject** are two buttons of one style on the first layer, with a link to the privacy page; nothing is pre-ticked, dimmed or trapped. The choice is stored in one strictly-necessary first-party cookie (default `consent`, six months, then the bar asks again). The component knows nothing about what the choice gates: it records it and dispatches `consent:change`. It makes no network request.

## Markup

The words and the privacy link are the site's own. The bar is `hidden` in the markup, so with JavaScript off nothing shows and nothing is recorded.

```html
<div class="site-consent" data-consent hidden role="region" aria-label="Cookies" tabindex="-1">
<div class="consent-inner">
<p>We count visits on our own server, only if you agree. <a href="/privacy">Privacy</a></p>
<div class="consent-actions">
<button type="button" data-consent-accept>Accept</button>
<button type="button" data-consent-reject>Reject</button>
</div>
</div>
</div>
<!-- anywhere, e.g. the footer's legal links: -->
<a href="/privacy" data-consent-open>Cookie settings</a>
<script type="module" src="/_vendored/site-consent/site-consent.js"></script>
```

Optional attributes on the bar: `data-consent-cookie="name"` (letters, digits, `_`, `-`; default `consent`) and `data-consent-days="183"`. An invalid value leaves the bar hidden and logs one warning.

## Contract

- **First visit:** the bar shows, without taking focus. **Accept** or **Reject** stores `granted` / `denied`, hides the bar and dispatches `consent:change` on `document` with `detail: { granted }` (`true` or `false`), only when the choice differs from the stored one.
- **Later loads:** the stored choice suppresses the bar and dispatches nothing. Read it with `import { getConsent } from '/_vendored/site-consent/site-consent.js'` (`true`, `false`, or `null` when none or expired) and subscribe to `consent:change` for what happens next.
- **Reopen and withdraw:** any `[data-consent-open]` link reopens the bar and moves focus to it; one click on **Reject** then withdraws. Escape closes a reopened bar unchanged. Focus returns to the link.
- **Page space:** while the bar shows, `--consent-h` carries its height and the page keeps that clearance at the bottom and for focused controls (WCAG 2.4.11).

Cookie: `Path=/; SameSite=Lax`, `Secure` on https. Styled only from [`site-tokens`](../site-tokens/) values, so it follows the site's brand; it needs no other component.

## Files

| File | Role |
| --- | --- |
| `site-consent.css` | Styles |
| `site-consent.js` | Behaviour (an ES module; the page works without it) |

## How to vendor

Copy this folder **verbatim** into the site's static source (for example `content/static/_vendored/site-consent/`) and declare it in the site's `.fleet.toml` `[vendored]` table; re-vendor with `/propagate-vendored site-consent`, never by hand. Do not edit the files per site. Load order and the whole set: [`../README.md`](../README.md).
