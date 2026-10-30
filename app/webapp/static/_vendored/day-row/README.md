# `day-row` — an action-row led by a date tile

The fleet's **date-keyed row** (`~/.claude/design.md` → action-row, "date tile", `ferraroroberto/fleet-config#1356`): an [`action-row`](../action-row/) whose **one leading slot is a date tile**, the weekday over the day number in a 44px square, today tinted `accent-soft`, all text at least 14px. The title then says what the day *is* ("Booked", "Holiday") and the one context line gives the reason. A chip appears **only for an exception**, and a chevron **only when the row opens something**.

Normalized from parking-manager's day row (`parking-manager#113`, `#114`), where one renderer served Home's coming days, a live view and a holidays list. It stops the next date-keyed app from drawing its own (`project-scaffolding#350`). Its sibling for a strip or a month grid is [`day-marks/`](../day-marks/).

## Files

| File | Role |
| --- | --- |
| `day-row.css` | Visual contract: the row's `rows.lg` height, the main button as a row, the date tile, the exception chip, the chevron. References design tokens only. Loads **after** `action-row.css`. |
| `day-row.js` | `dayRow({day, title, ...})` builds one `li.action-row.day-row`. Every string goes in with `textContent`, never HTML. |
| `day-row.html` | Markup skeleton to copy when the page is static. |

It also needs the vendored `icons/` sprite on the page, for `i-chevron-right`. It does **not** need `icon-button/`: the row has no glyph-only control (link it anyway when the page uses `action-row.css`, which is itself linked with it).

## How to vendor

1. Copy this `day-row/` folder **verbatim** into your app's static dir (`app/webapp/static/_vendored/day-row/`) next to `action-row/` and `icons/`. Do **not** edit `day-row.css` or `day-row.js` per-app.
2. Link the two stylesheets in this order (`day-row.css` restates a few `action-row.css` rules at higher specificity, so it wins either way, but keep the order):
   ```html
   <link rel="stylesheet" href="/static/_vendored/action-row/action-row.css">
   <link rel="stylesheet" href="/static/_vendored/day-row/day-row.css">
   ```
3. Build rows with the builder, into a `ul.action-rows` inside a `.card.action-list`:
   ```js
   import { dayRow } from '/static/_vendored/day-row/day-row.js';
   list.appendChild(dayRow({
     day: '2026-09-14', title: 'Booked', meta: 'Spot 12 · until 18:00', today: true,
     onOpen: (row) => openDaySheet(row.dataset.day),
   }));
   ```

## Markup contract

```html
<li class="action-row day-row" data-day="2026-09-15" data-status="no_spot">
  <button type="button" class="action-row-main day-row-main">     <!-- a <div> + day-row-main--static when it opens nothing -->
    <span class="date-tile [is-today]">
      <span class="date-tile-sr">Tuesday 15 September</span>      <!-- the whole date, for a screen reader -->
      <span class="date-tile-dow" aria-hidden="true">Tue</span>
      <span class="date-tile-num" aria-hidden="true">15</span>
    </span>
    <span class="action-row-text">
      <span class="action-row-title">Booked</span>
      <span class="action-row-meta">No spot assigned yet</span>   <!-- optional -->
    </span>
    <span class="day-row-chip" data-tone="danger">No spot</span>  <!-- optional, an exception only -->
    <svg class="icon day-row-chevron" aria-hidden="true"><use href="#i-chevron-right"></use></svg>  <!-- only when it opens something -->
  </button>
</li>
```

- **The date tile is the one leading slot.** It sits **inside** `.action-row-main`, so it is part of the tap target, like an avatar. A row never also carries a favorite, a check or an avatar. It is `min-width` and `min-height` `--row-sm` (44px, the floor), `rounded.md`, `neutral-soft` at rest and `accent-soft` with `accent-text` when `is-today`. The weekday is `body-sm` at 600, the number `body` at 700 in tabular figures. Both visible lines are `aria-hidden`; `.date-tile-sr` carries the full date, so a screen reader reads "Tuesday 15 September, Booked, No spot assigned yet".
- **Height is `--row-lg` (60px) always.** The tile plus the main button's padding is taller than the one-line `--row-md`, so a row without a context line is the same height as one with.
- **Title and context** are `action-row`'s: `body` at 600 and one `body-sm` muted line, each one line, ellipsized (`day-row.css` keeps the context line to one line, although `action-row`'s meta now wraps to two, `project-scaffolding#396`). `dayRow` also sets each as the element's `title`, so the full text is one hover or long-press away. A date row that needs more is a detail sheet, which the row opens.
- **The chip is for an exception only** (design.md "status chip"). `data-tone` is `danger` (broken: booked with no spot), `attention` (needs the user: a booking to cancel elsewhere) or `accent` (in progress). A holiday, a day off and every normal state get **no chip**, and success is never one. With no recognised tone the chip is a plain `neutral-soft` count, never a state. The text is `body-sm` at 600 in the tone's `*-text` on its 16% tint, which holds AA in both themes.
- **`onOpen` makes the row a real `<button>`** (Enter and Space for free) with a chevron; the callback gets the row, so `row.dataset.day` is the key. Without it the main element is a `<div>` with `day-row-main--static`: no pointer, no press tint, no chevron.
- **`today: true`** tints the tile and sets `aria-current="date"` on the main element. At most one row per list.
- **`status`** is kept as `data-status` and never styled; it is your hook (a test, an `is-past` rule of your own).
- **`locale`** (BCP 47, optional) sets the weekday text and the spoken date; the browser's own when omitted. The tile grows past 44px for a long weekday and never shrinks below it.
- **No app data.** The builder takes the day, the words and the exception as arguments. Which of your states earns a chip, and in which tone, is yours to decide and is the part that stays app-side.

## Required design tokens

| Token | Light value | Used for |
| --- | --- | --- |
| `--row-sm` | `44px` | date tile floor (`hit-target.min`) |
| `--row-lg` | `60px` | row height |
| `--gap` | `12px` | tile ↔ text ↔ chip gap |
| `--radius-md` | `12px` | date tile |
| `--radius-pill` | `9999px` | chip |
| `--ink` | `#1f2328` | tile and chip text at rest |
| `--muted` | `#656d76` | chevron |
| `--neutral-soft` | `color-mix(in srgb, var(--muted) 16%, transparent)` | tile and chip fill at rest |
| `--accent-soft` | `color-mix(…16%…)` | today's tile and the accent chip |
| `--accent-text` | `#0550ae` | today's tile text, accent chip text |
| `--deficit` | `#cf222e` | danger chip tint (design.md `danger`) |
| `--danger-text` | `#a40e26` | danger chip text |
| `--attention` | `#9a6700` | attention chip tint |
| `--attention-text` | `#7d4e00` | attention chip text |
| `--font-body` | `1rem` | day number |
| `--font-body-sm` | `0.875rem` | weekday, chip (14px, the text floor) |
| `--icon-inline` | `16px` | chevron |

Plus everything `action-row/` requires (`--row-md`, `--line-muted`, `--space-sm`, …).

## Don't diverge

`day-row.css` and `day-row.js` are vendored verbatim: to change the contract, change it **here in `project-scaffolding`** and re-vendor downstream. Don't add a second leading slot, a favorite, a kebab or a visible verb to a day row, don't shrink the tile under 44px or its text under 14px, don't give a normal day a chip, and don't colour a row. An app that grew its own `.day-row` / `.date-tile` drops it for these classes when it re-vendors. Streamlit POC spikes are exempt.
