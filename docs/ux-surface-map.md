# UX surface map

Every fleet web app keeps one map of everything a person can see and do in it: each screen, tab, drill-in, menu and kebab, sheet, dialog, popover, Settings row, empty, error and loading state, gesture and keyboard path, with how it is reached, what is on it, what each control does and the decision behind it. This page is the convention; [templates/ux-surface-map.md](templates/ux-surface-map.md) is the file an app copies to start its own.

## Why a map

A layout change (a wider measure, a new band, a moved nav) has to be checked surface by surface, and a design review only measures the surfaces its walk happens to open. Prose about the main views is not enough: when one fleet app's surfaces were walked by hand, the walk found 74 surfaces, the app's own view docs described 53 of them, 17 more were described only in unrelated docs, 4 were not described anywhere and 3 were described wrongly. A complete map turns "check every surface" from memory into a list, and gives each surface a name that code, tests and reviews can share.

## Where it lives

One file per web app: `docs/ux-surface-map.md` in the app's own repo. A repo serving two apps keeps one map per app, each named in its own `docs/` page. Streamlit spikes and public static sites are exempt.

## What counts as a surface

Anything a person can land on, open or perform as a unit:

- **Screens and tabs:** each nav destination, and each drill-in or pane reached from one (a detail drawer, a split pane, a sub-page).
- **Overlays:** every `<dialog>`, sheet, popover, menu, kebab, picker, toast and banner, whether it sits in the markup or is built in JS.
- **Settings:** each Settings group and each row that opens something or holds a choice.
- **States:** the empty, error, loading and gated renderings of a surface, when they show different controls or copy.
- **Inputs that are not elements:** gestures (swipes, drag and drop) and keyboard paths (shortcuts, the command palette's commands).

A single button is not a surface: it is listed under the surface it sits on, in that surface's *Does* line.

## Entry shape

Each surface is one entry: a paragraph that opens with its id in backticks, in bold with its title, then labelled fields.

```markdown
**`today.row-menu` Row menu** — *Root:* `data-surface`. *Reach:* the row's kebab, a right-click, `.` on a focused row. *Holds:* the row actions in their Settings order. *Does:* each action applies to the row and offers Undo. *States:* actions the task does not support are hidden. *Why:* one table of actions feeds the menu, the keys and the swipes.
```

| Field | What it says |
|---|---|
| *Root* | `data-surface` when an element in the code carries the id; `none — <reason>` when the surface has no element of its own (a gesture, a key, a state drawn inside another surface's root). A root-less entry always gives its reason. |
| *Reach* | Every way to get there: tap paths, keys, deep links, what opens it automatically. |
| *Holds* | What is on it, in order. |
| *Does* | What each control does, by its visible label. |
| *States* | Empty, error, loading, gated (a feature switched off), signed-out. |
| *Why* | The decision behind it, when the choice was deliberate. |

Add *Phone* and *Desktop* where the two renderings differ; a field without either holds for both. Group entries under `##` headings by area (Chrome, each nav destination, Settings, overlays, keys, states). Free prose between entries (ground rules, layout bands, where state lives) is welcome; only paragraphs that open with a bold backticked id are entries.

## Ids

- An id is lowercase letters and digits in segments joined by `.` or `-` (`^[a-z0-9]+(?:[.-][a-z0-9]+)*$`), the same form the e2e capture hook takes, so one id names the surface in the map, in the markup and in a test's `surface(page, "<id>")` call.
- Prefer `<area>.<surface>`, such as `today.row-menu` or `settings.theme`. Short area-number ids (`rw-4`) work too, but an id is never renumbered when entries are reordered.
- An id is stable for the life of the surface. Renaming a surface's title keeps its id; removing the surface removes its entry and every `data-surface` that carried it, in the same change.
- One id names one surface. A surface drawn two ways (a popover with a mouse, a sheet on a phone) keeps one id and one entry, with *Phone* and *Desktop* lines.

## The surface graph

The map holds one Mermaid `flowchart` of how surfaces connect: a node per surface (labelled with its title), an edge per way to reach it, labelled when the path is not obvious. It answers "where can I get to from here" and shows the shared surfaces (the one row, the one drawer, the one picker) that many paths feed.

## Code carries the id

The surface's root element carries `data-surface="<id>"`, the same id as its entry:

```html
<dialog id="quick-add" data-surface="strip.quick-add" data-track-view="quick-add">
```

A surface built in JS gets its id where it is built, as a constant string:

```js
const menu = document.createElement('div');
menu.setAttribute('role', 'menu');
menu.dataset.surface = 'today.row-menu';
```

- The value is always a string literal, never built from content or state.
- The root is the element that appears and disappears with the surface: the `<dialog>`, the sheet's container, the tab panel, the drill-in's pane. Elements that are surfaces by their markup (a `<dialog>`, an element with `role` `dialog`, `alertdialog`, `menu` or `tabpanel`, an element with a `popover` attribute) always carry one; screens, drill-ins and states carry one where they have a root of their own.
- A surface a vendored component builds is stamped by the app's call site, since the component's code is shared by every app.
- `data-surface` names a surface for the map, the tests and the design walk; it is independent of `data-track-view`, which names a view for the usage log, though the two often hold the same value.

## Keeping it true

A change that adds, removes, renames or reshapes a user-visible surface updates the map in the same PR, including the entry's *Why* when the choice was deliberate, and adds or removes the matching `data-surface`. A surface's entry and its attribute appear and disappear together.

The gate holds this deterministically: the [UX surface ratchet](ux-surface-ratchet.md) fails a change that adds a surface root with no `data-surface`, an id with no entry, an entry no element carries, or one id on two surfaces, beyond the app's committed baseline. It sees what the markup and the JS declare; a screen or state built with no id at all is caught by the design-review and e2e walk, which reports every surface it opened that carries no `data-surface`.

## Starting a map

1. Copy [templates/ux-surface-map.md](templates/ux-surface-map.md) to the app's `docs/ux-surface-map.md`.
2. Walk the running app on a phone and a desktop width, light and dark: open every tab, every control that opens something, every Settings row, every gated feature on and off, and the empty and error states. Write one entry per surface as you go.
3. Read the markup and the JS for surfaces the walk did not reach (a dialog only an error opens, a picker only one path uses) and add them.
4. Give each surface root its `data-surface`.
5. Draw the surface graph last, from the entries.
6. Record, at the bottom of the map, the date of the walk, the build it was made against and the widths and themes covered.
