# `chip` — a toggle pill for a filter or a day set

The fleet's canonical **toggle chip**: a pill with `aria-pressed` that joins or leaves a filter or a set, with an optional trailing count. It is the shape a store filter (`All 24`, `North 9`), a weekday set (`Mon`, `Tue`, …) and a zone strip share. Any number of chips in a group may be pressed at once.

It is the "Bucket 3" toggle chip of the [`button` README's](../button/README.md#bespoke-buttons-which-component-each-shape-moves-to) bespoke-button classification: two apps drew the same pill, so it is one component rather than two local classes.

**One choice among 2–5 peers is not this shape.** A control where choosing one option unchooses the others is a [`segmented`](../segmented/); more than five is a [`select-native`](../select-native/). A chip is for membership: each one is on or off by itself.

## Files

| File | Role |
| --- | --- |
| `chip.css` | Visual contract: the pill, the pressed state, the trailing count, the 44px hit area, the wrapping and the scrolling group. References design tokens only. |
| `chip.html` | Markup skeleton to copy and adapt (a wrapping group with counts and a scrolling strip). |

## How to vendor

1. Copy this `chip/` folder **verbatim** into your app's static dir (`app/webapp/static/_vendored/chip/`). Do **not** edit `chip.css` per-app.
2. Link the CSS:
   ```html
   <link rel="stylesheet" href="/static/_vendored/chip/chip.css">
   ```
3. Paste the skeleton, adapt the labels, the `data-*` values and the group's `aria-label`, and wire the toggle (below).

## Markup contract

```html
<div class="chip-group" role="group" aria-label="Stores">
  <button type="button" class="chip" aria-pressed="true" data-value="all">All <span class="chip-count">24</span></button>
  <button type="button" class="chip" aria-pressed="false" data-value="north">North <span class="chip-count">9</span></button>
</div>
```

- **`.chip-group`** is the container, a `role="group"` with an accessible name. It wraps onto further rows by default. It carries no outer margin, so place it with your own layout.
- **`.chip-group--scroll`** keeps the chips on one line that scrolls sideways inside its own box (a zone strip). The page never gains a horizontal scroll. Use it only where one line is the point; a short set reads better wrapped.
- **`.chip`** is each pill, a `<button type="button">`. It carries `aria-pressed="true"` or `"false"`. Flipping it is the caller's job, because what the set drives differs per use (a filter, a day set):
  ```js
  group.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip || chip.disabled) return;
    chip.setAttribute('aria-pressed', String(chip.getAttribute('aria-pressed') !== 'true'));
  });
  ```
  When the toggle writes to a server, flip it after the write lands, or roll it back on failure, so the pressed fill never lies about the state.
- **`.chip-count`** is the optional trailing number, inside the button after the label. It is muted at rest and takes the chip's own colour when pressed.
- **Labels** are short and never wrap. A chip is never narrower than 44px, so a one-letter chip is still a target.
- **Unavailable chips** carry `disabled` and a `title` saying why. They keep their label colour; the cursor and the title say it is unavailable. Never use opacity.

## State, targets and contrast

- **Pressed is the fill and the border:** `accent-soft` fill, `accent` border and `accent-text` label. At rest the chip is `card` with a `line` border and an `ink` label. The label weight is the same in both states, so a press never changes a chip's width or moves a neighbour.
- Chips are 36px tall (`--control-h`). A `::before` band grows the hit area to the 44px floor (`--row-sm`) vertically, and the chip's `min-width` does the same horizontally, so the group's 8px gap keeps neighbouring targets from overlapping (design.md "Touch targets").
- The label contrast is asserted by the gallery harness in both themes: `ink` on `card` at rest, `accent-text` on the composited `accent-soft` pressed, and the muted count on `card` at rest.

## Required design tokens

| Token | Light value | Used for |
| --- | --- | --- |
| `--card` | `#ffffff` | resting fill, and the surface the pressed fill composites over |
| `--line` | `#d1d9e0` | resting border |
| `--ink` | `#1f2328` | resting label |
| `--muted` | `#656d76` | resting count, hover tint (10% mix) |
| `--accent` | `#0969da` | pressed border |
| `--accent-soft` | `color-mix(in srgb, var(--accent) 16%, transparent)` | pressed fill |
| `--accent-text` | `#0550ae` | pressed label |
| `--control-h` | `36px` | chip height |
| `--row-sm` | `44px` | hit-target floor, minimum chip width |
| `--radius-pill` | `9999px` | the pill corners |
| `--font-label` | `0.875rem` | label text |
| `--font-caption` | `0.75rem` | count text |
| `--space-xs` | `4px` | label ↔ count gap, scroll-strip padding |
| `--space-sm` | `8px` | the gap between chips |
| `--space-md` | `16px` | horizontal padding |

## Don't diverge

`chip.css` is vendored verbatim: to change the contract, change it **here in `project-scaffolding`** and re-vendor downstream. Don't add a per-app pill class, tint the pressed state with another hue, or fade the unpressed chips; those are the shapes this component exists to retire. If your own CSS declares a selector this file touches, use longhand properties or a disjoint media condition — a shorthand at equal specificity is decided by source order. Streamlit POC spikes are exempt.
