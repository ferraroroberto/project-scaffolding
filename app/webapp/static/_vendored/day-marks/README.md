# `day-marks` — one shape per day

The fleet's **day marks** (`~/.claude/design.md` → "day marks", `ferraroroberto/fleet-config#1356`): a month grid or a two-week strip draws each day as **its number over one small shape** for its state. **State is a mark, never a fill**: no cell is filled with a status colour. Colour only **rings an exception**, in `danger` (broken) or `attention` (needs the user), so a problem day is the one ringed cell in the grid. An expected non-day (a holiday, a day off) gets the neutral "off" dash, not amber. The legend lists **marks, not swatches**.

Normalized from parking-manager's strip and month grid (`parking-manager#114`, `#115`), so the next date-keyed app doesn't re-invent them (`project-scaffolding#350`). Its sibling for a list is [`day-row/`](../day-row/).

| Mark | Shape | Colour | Means (default legend words) |
| --- | --- | --- | --- |
| `booked` | filled dot | `fg` | Booked |
| `will` | ring (hollow dot) | `fg` | Will book |
| `extra` | diamond | `fg` | Extra day |
| `looking` | half-filled ring | `accent` | Looking (work in progress) |
| `off` | 2px dash | `muted` | Not booked on purpose |

Each is distinct in shape alone, so **no state is told by colour only**, and each sits in a 10px square slot whatever its shape.

## Files

| File | Role |
| --- | --- |
| `day-marks.css` | The five CSS-drawn marks, the ring (`.day-ring[data-ring]`) and the legend list. References design tokens only. |
| `day-marks.js` | `MARK_WORDS` (the legend's `[mark, label]` pairs), `markHtml(mark)` (the mark's span, or `''`) and `legendEl(words?)` (a `ul.day-legend`). |
| `day-marks.html` | Markup skeleton to copy. |

## How to vendor

1. Copy this `day-marks/` folder **verbatim** into your app's static dir (`app/webapp/static/_vendored/day-marks/`). Do **not** edit `day-marks.css` or `day-marks.js` per-app.
2. Link the stylesheet and use the builders:
   ```html
   <link rel="stylesheet" href="/static/_vendored/day-marks/day-marks.css">
   ```
   ```js
   import { markHtml, legendEl } from '/static/_vendored/day-marks/day-marks.js';
   cell.innerHTML = `<span class="day-num">${n}</span>${markHtml(mark)}`;
   legendHost.appendChild(legendEl());
   ```

## Markup contract

```html
<button type="button" class="day-cell day-ring" data-ring="danger" aria-label="Tuesday 15, booked, no spot assigned">
  <span class="day-num">15</span>
  <span class="day-mark" data-mark="booked" aria-hidden="true"></span>
</button>
```

- **`.day-mark[data-mark]`** is an empty, `aria-hidden` span the CSS draws. `markHtml()` returns `''` for a name that is not one of the five, so a stray value never draws a stray shape.
- **The cell is yours.** A strip and a month grid lay a day out differently, so `.day-cell` / `.day-num` are your app's classes. Give the cell a **10px mark row** (`grid-template-rows: auto 10px`), so a day with no mark keeps its slot and the numbers line up. A cell carries **at most one mark**.
- **The ring** is `class="day-ring" data-ring="danger|attention"` on the cell: a 2px inset ring, so it never resizes the cell. Any other `data-ring` draws nothing. Only an exception is ringed; never ring a normal day, never fill a cell, never use red for a normal state. A ring is explained by the day's own detail sheet, not the legend. A selection ring is the app's own and composes with this one in its own `box-shadow` list.
- **The accessible name says what the day is** ("Tuesday 15, booked, no spot assigned"). The mark is decoration; a screen reader never needs it.
- **The legend** is `legendEl()`: one `li` per mark, the mark then its words, `body-sm` in `fg`, two columns. Pass a filtered or relabelled `[mark, label]` list to match an app that never uses `looking`, or names the marks differently. A day opens its **detail sheet** (`modal`), the pane at `layout.wide`.

## Mapping your states

Which of your states draws which mark, and which states earn a ring, is the app's own data and stays out of this component. The shape of that map, with invented states:

```js
const MARK = { confirmed: 'booked', conflict: 'booked', searching: 'looking', planned: 'will', closed: 'off' };
const RING = { conflict: 'danger', to_cancel: 'attention' };   // "needs a manual action elsewhere" is attention, never danger
```

A holiday or a day off is expected, so it gets the neutral `off` mark with **no ring**. "Needs a manual action elsewhere" is `attention`; `danger` is only for what is actually broken.

## Required design tokens

| Token | Light value | Used for |
| --- | --- | --- |
| `--ink` | `#1f2328` | `booked`, `will`, `extra` marks; legend text |
| `--accent` | `#0969da` | `looking` mark |
| `--muted` | `#656d76` | `off` dash |
| `--deficit` | `#cf222e` | danger ring (design.md `danger`) |
| `--attention` | `#9a6700` | attention ring |
| `--font-body-sm` | `0.875rem` | legend (14px, the text floor) |
| `--space-sm` | `8px` | mark ↔ word gap in the legend |

## Don't diverge

`day-marks.css` and `day-marks.js` are vendored verbatim: to change the contract, change it **here in `project-scaffolding`** and re-vendor downstream. Don't add a sixth mark, fill a cell with a status colour, tell a state by hue alone, or ring a normal day. Streamlit POC spikes are exempt.
