# `icon-tile` — the Home-screen rounded-square

The fleet's canonical **icon tile**: a squircle at `rounded.md` filled with **one** of the five `tile-*` colors (the fleet's only saturated surfaces), a centered feature-size Lucide glyph in `accent-fg`. The fill signals *category*, not state — never use a `tile-*` color anywhere else. Contract: `~/.claude/design.md` → `icon-tile` token block + "Component contracts".

## Files

| File | Role |
| --- | --- |
| `icon-tile.css` | Visual contract: the squircle + the five fill modifiers. References design tokens only. |
| `icon-tile.html` | Markup skeleton to copy and adapt. |

## How to vendor

1. Copy this `icon-tile/` folder **verbatim** into your app's static dir. Do **not** edit `icon-tile.css` per-app.
2. Link the CSS and paste the skeleton:
   ```html
   <link rel="stylesheet" href="/static/_vendored/icon-tile/icon-tile.css">
   ```
3. Icons come from the vendored [`icons/`](../icons/) sprite.

## Markup contract

```html
<span class="icon-tile icon-tile--blue">
  <svg class="icon"><use href="#i-NAME"></use></svg>
</span>
```

- Pick exactly **one** fill modifier (`--green|--blue|--purple|--orange|--yellow`).
- The glyph is always `accent-fg` (white) at `icons.size.feature` — don't recolor it per tile.

## Required design tokens

| Token | Light value | Used for |
| --- | --- | --- |
| `--tile-green` | `#1f883d` | fill |
| `--tile-blue` | `#0969da` | fill |
| `--tile-purple` | `#8250df` | fill |
| `--tile-orange` | `#bc4c00` | fill |
| `--tile-yellow` | `#bf8700` | fill |
| `--accent-fg` | `#ffffff` | glyph |
| `--radius-md` | `12px` | corners (`rounded.md`) |
| `--icon-feature` | `24px` | glyph size (`icons.size.feature`) |
| `--tile-size` | `48px` (proposed) | tile box |

**`--tile-size` note:** unlike every other value here, the tile box size has no shipped fleet instance behind it yet — `48px` is proposed from the GitHub-mobile look the identity is modelled on (glyph ½ the tile). The first adopting app (app-launcher, per the rollout plan) validates it; if it lands differently, update this README and `design.md` **together**.

## Don't diverge

`icon-tile.css` is vendored verbatim — to change the contract, change it **here in `project-scaffolding`** and re-vendor downstream. Streamlit POC spikes are exempt.
