# `nav` — floating bottom-tab navigation

The fleet's canonical **primary navigation**: a top segmented control on desktop that becomes a single floating bottom-tab pill on touch / installed-PWA. This is the navigation contract every fleet web app must *feel* identical on (see `~/.claude/design.md` → "Navigation & interaction").

## Files

| File | Role |
| --- | --- |
| `nav-tabs.js` | Behaviour. ESM module — `initNavTabs(opts)`. Discovers tabs/panes from the DOM, persists the active tab, keeps ARIA + roving `tabindex` in sync. |
| `nav-tabs.css` | Visual contract. The desktop segmented control + the `@media (pointer: coarse)` floating pill + the modal-hide rule. References design tokens only. |
| `nav-tabs.html` | Markup skeleton to copy and adapt (3 example tabs). |

## How to vendor

1. Copy this `nav/` folder **verbatim** into your app's static dir (e.g. `app/webapp/static/_vendored/nav/`). Do **not** edit `nav-tabs.js` / `nav-tabs.css` per-app — that is the drift this component removes. Per-app changes go in *your* markup and *your* token values only.
2. Paste the `nav-tabs.html` skeleton into your `index.html` and adapt the tabs (rename `data-tab` / `aria-controls` / ids, swap the SVG icon + emoji + label, add/remove `<button class="tab">` + matching `<section class="pane">` pairs). **Wrap your page content in `<main class="app">`** — the mobile stylesheet reserves bottom padding on `.app` so the floating bar never occludes content.
3. Link the CSS and set the tab count:
   ```html
   <link rel="stylesheet" href="/static/_vendored/nav/nav-tabs.css">
   ```
   ```css
   /* No tab-count variable is required: the mobile grid auto-fits 4–6 tabs. */
   ```
4. Wire up the switcher once the DOM is ready:
   ```js
   import { initNavTabs } from '/static/_vendored/nav/nav-tabs.js';
   const nav = initNavTabs({
     storageKey: 'my-app.tab',   // omit to disable PWA persistence
     onChange: (tab) => { /* lazy-load that pane, change poll rate, … */ },
   });
   ```

## Markup contract

```html
<nav class="tabs" role="tablist" data-active-tab="home">
  <button class="tab" data-tab="NAME" role="tab"
          aria-controls="PANE_ID" aria-selected="…"> … </button>
</nav>
<section id="PANE_ID" class="pane" role="tabpanel" aria-labelledby="…"> … </section>
```

Each `.tab` carries `data-tab` (its name) and `aria-controls` (the id of the pane it shows). Start every non-default `.pane` with `hidden` so there's no flash before JS runs. A tab may omit its pane (e.g. an external link) — only its button state toggles.

## Required design tokens

`nav-tabs.css` references these CSS custom properties — define them in your app's `:root` / `[data-theme="dark"]` blocks, **wired to `~/.claude/design.md` (+ `design.dark.md`)**. Don't copy the spec; point your tokens at it. Reference values (light) from the canonical implementation. The mobile geometry below is the phone-validated standard promoted from `home-automation` issue #118: measured from 1290px-wide iPhone screenshots of the GitHub/VLC apps (~3x CSS pixels), then validated live on Roberto's iPhone.

| Token | Light value | Used for |
| --- | --- | --- |
| `--card` | `#ffffff` | tab bar surface (desktop) |
| `--card-off` | `#f6f8fa` | active-tab fill |
| `--accent` | `#0969da` | active-tab text/icon |
| `--muted` | `#656d76` | inactive-tab text |
| `--line` | `#d1d9e0` | bar border, active-tab border (mobile) |
| `--space-xs` | `4px` | bar padding / gap (desktop) |
| `--gap` | `12px` | bottom-padding reserve |
| `--font-label` | `0.92rem` | tab label (desktop) |
| `--font-caption` | `0.78rem` | tab label (narrow desktop) |
| `--radius-md` | `12px` | bar corners (desktop) |
| `--radius-pill` | `9999px` | tab corners |
| `--radius-nav` | `30px` | floating bar corners (mobile) |
| `--bottom-tabs-height` | `61px` | floating bar height |
| `--bottom-tabs-margin` | `21px` | floating bar inset from left/right/physical bottom |
| `--bottom-tabs-pill-height` | `53px` | per-tab pill height (mobile) |
| `--bottom-tabs-padding` | `4px` | mobile bar inner padding |
| `--bottom-tabs-gap` | `4px` | mobile tab gap |
| `--bottom-tabs-icon` | `20px` | mobile SVG icon size |
| `--bottom-tabs-label` | `11px` | mobile label font size |
| `--tabbar-bg` | `rgba(255,255,255,0.85)` | floating bar glass fill |
| `--tabbar-border` | `rgba(31,35,40,0.12)` | floating bar border |

## The modal-hide rule

The floating bar hides whenever a modal is open so it never floats over a dialog:

- Any native `<dialog open>` → handled automatically (`body:has(dialog[open]) .tabs`).
- A non-`<dialog>` overlay (e.g. a custom login screen) → add the class `nav-hidden` to `<body>` while it's open.

## Scroll-pinning (mobile Safari)

The mobile stylesheet positions the floating bar `fixed; bottom: …` against the **layout** viewport. iOS Safari's dynamic bottom toolbar collapses on scroll-down and re-expands on scroll-up, resizing the layout viewport and dragging a bottom-anchored fixed element up then down — the bar rides loose instead of staying locked.

`initNavTabs` fixes this automatically: it installs a `VisualViewport` listener that translates the bar up by the slice of layout viewport hidden below the visible rect, so the bar's CSS `bottom` inset is measured from the *visible* bottom edge. It's gated to the coarse-pointer / narrow floating-bar mode (desktop's sticky top control is untouched) and feature-detected on `window.visualViewport` (older browsers fall back to the CSS-only behaviour — no error). No call-site change is needed.

**Recommended app-level hardening:** set `overscroll-behavior: none` on `html, body` in your app's stylesheet to kill rubber-band overscroll drag at the document edges. This lives in the consuming app, not the component, because the document scroller (`body`) is the app's, not the nav's.

## Don't diverge

`nav-tabs.js` and `nav-tabs.css` are **vendored verbatim** — the same "copy byte-for-byte, never edit per-app" rule as the tray's `single_instance.py` / `tray_lifecycle.ps1`. If the contract needs to change, change it **here in `project-scaffolding`** and re-vendor downstream; don't fork it in a consuming app. Streamlit POC spikes are exempt — they don't serve this PWA shell.
